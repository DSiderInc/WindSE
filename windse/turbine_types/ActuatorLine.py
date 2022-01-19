import numpy as np
import scipy.interpolate as interp
import glob

from windse import windse_parameters
if windse_parameters.dolfin_adjoint:
    from windse.blocks import blockify, ActuatorLineForceBlock

from . import GenericTurbine

from . import Constant, Expression, Function, Point, assemble, dot, dx

'''
FIXME After Jeff Meeting 1/13/22

1. figure out how to get rid of u_k in ActuatorLineForceBlock.py (kind of done)
2. take the derivatives with respect to mpi_u_fluid (kind of done)

'''

class ActuatorLine(GenericTurbine):

    def __init__(self, i,x,y,dom,imported_params=None):
        # Define the acceptable column of an wind_farm.csv imput file        
        self.yaml_inputs = ["HH", "RD", "yaw", "yaw", "rpm", "read_turb_data", "blade_segments", "use_local_velocity", "chord_factor", "gauss_factor"]

        # Init turbine
        super(ActuatorLine, self).__init__(i,x,y,dom,imported_params)

        # blockify custom functions so dolfin adjoint can track them
        if self.params.performing_opt_calc:
            block_kwargs = {
                # "construct_sparse_ids":self.construct_sparse_ids,
                "control_types": self.params["optimization"]["control_types"],
                "turb": self
            }
            self.build_actuator_lines = blockify(self.build_actuator_lines,ActuatorLineForceBlock,block_kwargs=block_kwargs)


        # init some flags
        self.first_call_to_alm = True
        self.simTime_prev = None
        self.DEBUGGING = False

    def get_baseline_chord(self):
        '''
        This function need to return the baseline chord as a numpy array with length num_blade_segments
        '''
        return self.baseline_chord


    def load_parameters(self):

        self.type = self.params["turbines"]["type"]
        self.HH = self.params["turbines"]["HH"]
        self.RD = self.params["turbines"]["RD"]
        self.yaw = self.params["turbines"]["yaw"]
        self.rpm = self.params["turbines"]["rpm"]
        self.read_turb_data = self.params["turbines"]["read_turb_data"]
        self.blade_segments = self.params["turbines"]["blade_segments"]
        self.use_local_velocity = self.params["turbines"]["use_local_velocity"]
        self.chord_factor = self.params["turbines"]["chord_factor"]
        self.gauss_factor = self.params["turbines"]["gauss_factor"]

    def compute_parameters(self):

        # compute turbine radius
        self.radius = 0.5*self.RD

    def create_controls(self, initial_call_from_setup=True):

        if initial_call_from_setup:
            self.controls_list = ["x","y","cl","cd","chord","yaw"] # this is just part of the function as an example of the types of controls 

            self.mx     = Constant(self.x, name="x_{:d}".format(self.index))
            self.my     = Constant(self.y, name="y_{:d}".format(self.index))
            self.myaw   = Constant(self.yaw, name="yaw_{:d}".format(self.index))

        else:
            # Assign the chord, twist, cl, and cd values into a list of constants
            self.mchord = []
            self.mtwist = []
            self.mcl = []
            self.mcd = []

            for k in range(self.num_blade_segments):
                self.mchord.append(Constant(self.chord[k]))
                self.mtwist.append(Constant(self.twist[k]))
                self.mcl.append(Constant(self.cl[k]))
                self.mcd.append(Constant(self.cd[k]))

    def lookup_lift_and_drag(self, u_rel, twist, blade_unit_vec):

        def get_angle_between_vectors(a, b, n):
            a_x_b = np.dot(np.cross(n, a), b)

            norm_a = np.sqrt(a[0]*a[0] + a[1]*a[1] + a[2]*a[2])
            norm_b = np.sqrt(b[0]*b[0] + b[1]*b[1] + b[2]*b[2])

            c1 = a_x_b/(norm_a*norm_b)
            c1 = np.clip(c1, -1.0, 1.0)
            aoa_1 = np.arcsin(c1)

            c2 = np.dot(a, b)/(norm_a*norm_b)
            c2 = np.clip(c2, -1.0, 1.0)
            aoa_2 = np.arccos(c2)
            
            if aoa_2 > np.pi/2.0:
                if aoa_1 < 0:
                    aoa_1 = -np.pi - aoa_1
                else:
                    aoa_1 = np.pi - aoa_1
            
            aoa_1_deg = aoa_1/np.pi*180.0
            
            return aoa_1

        # Initialize the real cl and cd profiles
        real_cl = np.zeros(self.num_blade_segments)
        real_cd = np.zeros(self.num_blade_segments)

        # fp = open(problem.aoa_file, 'a')

        tip_loss = np.zeros(self.num_blade_segments)

        for k in range(self.num_blade_segments):
            # Get the relative wind velocity at this node
            wind_vec = u_rel[:, k]

            # Remove the component in the radial direction (along the blade span)
            wind_vec -= np.dot(wind_vec, blade_unit_vec[:, 1])*blade_unit_vec[:, 1]

            # aoa = get_angle_between_vectors(arg1, arg2, arg3)
            # arg1 = in-plane vector pointing opposite rotation (blade sweep direction)
            # arg2 = relative wind vector at node k, including blade rotation effects (wind direction)
            # arg3 = unit vector normal to plane of rotation, in this case, radially along span
            aoa = get_angle_between_vectors(-blade_unit_vec[:, 2], wind_vec, -blade_unit_vec[:, 1])

            # Compute tip-loss factor
            if self.rdim[k] < 1e-12:
                tip_loss[k] = 1.0
            else:
                loss_exponent = 3.0/2.0*(self.radius-self.rdim[k])/(self.rdim[k]*np.sin(aoa))
                acos_arg = np.exp(-loss_exponent)
                acos_arg = np.clip(acos_arg, -1.0, 1.0)
                tip_loss[k] = 2.0/np.pi*np.arccos(acos_arg)

            # Remove the portion of the angle due to twist
            aoa -= twist[k]

            # Store the cl and cd by interpolating this (aoa, span) pair from the tables
            real_cl[k] = self.lookup_cl(aoa, self.rdim[k])
            real_cd[k] = self.lookup_cd(aoa, self.rdim[k])

            # Write the aoa to a file for future reference
            # fa.write('%.5f, ' % (aoa/np.pi*180.0))

        # fp.close()
        return real_cl, real_cd, tip_loss


    def build_actuator_lines(self, u, inflow_angle, fs, dfd=None):

        # Create TF each time
        tf = Function(fs.V)

        # Read cl and cd from the values specified in problem manager
        twist = np.array(self.mtwist, dtype = float)
        chord = np.array(self.mchord, dtype = float)

        cl = np.array(self.mcl, dtype = float)
        cd = np.array(self.mcd, dtype = float)

        # Initialze arrays depending on what this function will be returning
        if dfd is None:
            tf_vec = np.zeros(np.size(self.coords))
            tf_vec_for_power = np.zeros(np.size(self.coords))
            lift_force = np.zeros((np.shape(self.coords)[0], self.ndim))
            drag_force = np.zeros((np.shape(self.coords)[0], self.ndim))

        elif dfd == 'c_lift':
            cl = np.ones(self.num_blade_segments)
            dfd_c_lift = np.zeros((np.size(problem.coords), problem.num_blade_segments))

        elif dfd == 'c_drag':
            cd = np.ones(self.num_blade_segments)
            dfd_c_drag = np.zeros((np.size(self.coords), self.num_blade_segments))

        elif dfd == 'chord':
            chord = np.ones(self.num_blade_segments)
            dfd_chord = np.zeros((np.size(self.coords), self.num_blade_segments))

        # Convert the mpi_u_fluid Constant wrapper into a numpy array
        # FIXME: double check that this wrapping-unwrapping is correct
        mpi_u_fluid = np.copy(self.mpi_u_fluid_constant.values())

        # Treat each blade separately
        for blade_ct, theta_0 in enumerate(self.theta_vec):
            # If the minimum distance between this mesh and the turbine is >2*RD,
            # don't need to account for this turbine
            if self.min_dist > 2.0*self.RD:
                break

            # Generate a rotation matrix for this turbine blade
            Rx = self.rot_x(self.theta_ahead + theta_0)
            Rz = self.rot_z(float(self.myaw))

            # Rotate the blade velocity in the global x, y, z, coordinate system
            # Note: blade_vel_base is negative since we seek the velocity of the fluid relative to a stationary blade
            # and blade_vel_base is defined based on the movement of the blade
            blade_vel = np.dot(Rz, np.dot(Rx, -self.blade_vel_base))

            # Rotate the blade unit vectors to be pointing in the rotated positions
            blade_unit_vec = np.dot(Rz, np.dot(Rx, self.blade_unit_vec_base))

            # Rotate the entire [x; y; z] matrix using this matrix, then shift to the hub location
            blade_pos = np.dot(Rz, np.dot(Rx, self.blade_pos_base))
            blade_pos[0, :] += self.x
            blade_pos[1, :] += self.y
            blade_pos[2, :] += self.z

            # Get the velocity of the fluid at each actuator node
            # Read values from mpi_u_fluid (a [num_turbs x 3_dim*3_rotors*num_blade_segments] numpy array)
            if self.DEBUGGING:
                u_fluid = np.zeros((self.ndim, self.num_blade_segments))
                u_fluid[0, :] = 10.0

            else:
                start_pt = self.ndim*blade_ct*self.num_blade_segments
                end_pt = start_pt + self.ndim*self.num_blade_segments
                u_fluid = mpi_u_fluid[start_pt:end_pt]
                u_fluid = np.reshape(u_fluid, (self.ndim, -1), 'F')

            for k in range(self.num_blade_segments):
                u_fluid[:, k] -= np.dot(u_fluid[:, k], blade_unit_vec[:, 1])*blade_unit_vec[:, 1]

            # print(u_fluid)
            # print('MPI sim time = %.15e' % (simTime))
                            
            # Form the total relative velocity vector (including velocity from rotating blade)
            u_rel = u_fluid + blade_vel

            u_rel_mag = np.linalg.norm(u_rel, axis=0)
            u_rel_mag[u_rel_mag < 1e-6] = 1e-6
            u_unit_vec = u_rel/u_rel_mag
            
            if self.DEBUGGING:
                cl = 1*np.ones(self.num_blade_segments)
                cd = 1*np.ones(self.num_blade_segments)
                tip_loss = 1.0

            else:
                if self.lookup_cl is not None:
                    cl, cd, tip_loss = self.lookup_lift_and_drag(u_rel, twist, blade_unit_vec)

            # Calculate the lift and drag forces using the relative velocity magnitude
            rho = 1.0
            lift = tip_loss*(0.5*cl*rho*chord*self.w*u_rel_mag**2)
            drag = tip_loss*(0.5*cd*rho*chord*self.w*u_rel_mag**2)

            # Tile the blade coordinates for every mesh point, [numGridPts*ndim x problem.num_blade_segments]
            blade_pos_full = np.tile(blade_pos, (np.shape(self.coords)[0], 1))

            # Subtract and square to get the dx^2 values in the x, y, and z directions
            dx_full = (self.coordsLinear - blade_pos_full)**2

            # Add together to get |x^2 + y^2 + z^2|^2
            dist2 = dx_full[0::self.ndim] + dx_full[1::self.ndim] + dx_full[2::self.ndim]

            # Calculate the force magnitude at every mesh point due to every node [numGridPts x NumActuators]
            nodal_lift = lift*np.exp(-dist2/self.gaussian_width**2)/(self.gaussian_width**3 * np.pi**1.5)
            nodal_drag = drag*np.exp(-dist2/self.gaussian_width**2)/(self.gaussian_width**3 * np.pi**1.5)

            for k in range(self.num_blade_segments):
                # The drag unit simply points opposite the relative velocity unit vector
                drag_unit_vec = -np.copy(u_unit_vec[:, k])
                
                # The lift is normal to the plane generated by the blade and relative velocity
                lift_unit_vec = np.cross(drag_unit_vec, blade_unit_vec[:, 1])

                # All force magnitudes get multiplied by the correctly-oriented unit vector
                vector_nodal_lift = np.outer(nodal_lift[:, k], lift_unit_vec)
                vector_nodal_drag = np.outer(nodal_drag[:, k], drag_unit_vec)

                # print('MPI vec norm = %.15e' % np.linalg.norm(vector_nodal_lift))
                # print('MPI vec norm = %.15e' % np.linalg.norm(vector_nodal_drag))

                if dfd == None:
                    lift_force += vector_nodal_lift
                    drag_force += vector_nodal_drag

                elif dfd == 'c_lift':
                    for j in range(self.ndim):
                        dfd_c_lift[j::self.ndim, k] += vector_nodal_lift[:, j]

                elif dfd == 'c_drag':
                    for j in range(self.ndim):
                        dfd_c_drag[j::self.ndim, k] += vector_nodal_drag[:, j]

                elif dfd == 'chord':
                    for j in range(self.ndim):
                        dfd_chord[j::self.ndim, k] += vector_nodal_lift[:, j] + vector_nodal_drag[:, j]

                # Compute the total force vector [x, y, z] at a single actuator node
                actuator_lift = lift[k]*lift_unit_vec
                actuator_drag = drag[k]*drag_unit_vec

                # Note: since this will be used to define the force (torque) from fluid -> blade
                # we reverse the direction that otherwise gives the turbine force from blade -> fluid
                actuator_force = -(actuator_lift + actuator_drag)
                # actuator_force = -(actuator_lift - actuator_drag)

                # Find the component in the direction tangential to the blade
                tangential_actuator_force = np.dot(actuator_force, blade_unit_vec[:, 2])

                rotor_plane_force = np.dot(actuator_force, blade_unit_vec)
                # fx.write('%.5f, ' % (rotor_plane_force[0]))
                # fy.write('%.5f, ' % (rotor_plane_force[1]))
                # fz.write('%.5f, ' % (rotor_plane_force[2]))

                # Multiply by the distance away from the hub to get a torque
                actuator_torque = tangential_actuator_force*self.rdim[k]

                # Add to the total torque
                # FIXME: if we ever wanted to use this as a control it should be updated
                # so that the summation happens outside this function
                self.rotor_torque += actuator_torque

        # fx.write('\n')
        # fy.write('\n')
        # fz.write('\n')
        # fa.write('\n')
        # fx.close()
        # fy.close()
        # fz.close()
        # fa.close()

        # Output the numpy version of rotor_torque
        # problem.rotor_torque[turb_i] = self.rotor_torque_numpy_temp
        if self.rotor_torque > 0:
            self.rotor_torque_count[0] = 1

        if dfd == None:
            # The total turbine force is the sum of lift and drag effects
            turbine_force = drag_force + lift_force
            turbine_force_for_power = -drag_force + lift_force

            # print('MPI vec norm = %.15e' % np.linalg.norm(vector_nodal_lift))
            # print('MPI vec norm = %.15e' % np.linalg.norm(turbine_force))

            # Riffle-shuffle the x-, y-, and z-column force components
            for k in range(self.ndim):
                tf_vec[k::self.ndim] = turbine_force[:, k]
                tf_vec_for_power[k::self.ndim] = turbine_force_for_power[:, k]

            # Remove near-zero values
            tf_vec[np.abs(tf_vec) < 1e-12] = 0.0

            # Add to the cumulative turbine force
            tf.vector()[:] += tf_vec

        tf.vector().update_ghost_values()

        print('Max TF: ', tf.vector().max() - 0.026665983592878112)
        print('Min TF: ', tf.vector().min() - -0.22879677484292432)
        print('Max Lift: ', np.amax(lift) - 1604.506078981611)
        print('Max Drag: ', np.amax(drag) - 2205.459487502247)
        print('Max Nodal Lift: ', np.amax(nodal_lift) - 0.053743827932146535)
        print('Max Nodal Drag: ', np.amax(nodal_drag) - 0.07069602361087358)
        print('Rotor torque numpy:', self.rotor_torque - 117594.90448122297)

        if dfd == None:

            return tf

        elif dfd == 'c_lift':
            save_c_lift = False

            if save_c_lift:
                save_derivative_file(problem.params.folder+"timeSeries/",'dfdcl', dfd_c_lift)

            return dfd_c_lift

        elif dfd == 'c_drag':
            save_c_drag = False

            if save_c_drag:
                save_derivative_file(problem.params.folder+"timeSeries/",'dfdcd', dfd_c_drag)

            return dfd_c_drag

        elif dfd == 'chord':
            save_chord = False

            if save_chord:
                save_derivative_file(problem.params.folder+"timeSeries/",'dfdchord', dfd_chord)

            return dfd_chord


    def init_constant_alm_terms(self, fs):

        #================================================================
        # Get information about the mesh coordinates and distances
        #================================================================

        self.ndim = self.dom.dim

        # Get the coordinates of the vector function space
        self.coords = fs.V.tabulate_dof_coordinates()
        self.coords = np.copy(self.coords[0::self.ndim, :])

        # Resape a linear copy of the coordinates for every mesh point
        self.coordsLinear = np.copy(self.coords.reshape(-1, 1))

        bbox = self.dom.mesh.bounding_box_tree()
        turbine_loc_point = Point(self.x, self.y, self.z)
        node_id, dist = bbox.compute_closest_entity(turbine_loc_point)
        self.min_dist = dist

        #================================================================
        # Set turbine properties and calculate derived values
        #================================================================

        # Set the number of blades in the turbine
        self.num_blades = 3

        # Set the spacing pf each blade
        self.theta_vec = np.linspace(0.0, 2.0*np.pi, self.num_blades, endpoint = False)

        # Calculate the blade velocity
        self.angular_velocity = 2.0*np.pi*self.rpm/60.0
        self.tip_speed = self.angular_velocity*self.radius

        # Recommendation from Churchfield et al.
        # self.gaussian_width = 2.0*0.035*2.0*self.radius
        hmin = self.dom.mesh.hmin()/np.sqrt(3)
        self.gaussian_width = float(self.gauss_factor)*hmin

        if self.blade_segments == "computed":
            self.num_blade_segments = int(2.0*self.radius/self.gaussian_width)
        else:
            self.num_blade_segments = self.blade_segments

        # Calculate the radial position of each actuator node
        self.rdim = np.linspace(0.0, self.radius, self.num_blade_segments)

        # Calculate width of an individual blade segment
        # w = rdim[1] - rdim[0]
        self.w = (self.rdim[1] - self.rdim[0])*np.ones(self.num_blade_segments)
        self.w[0] = self.w[0]/2.0
        self.w[-1] = self.w[-1]/2.0

        #================================================================
        # Set constant structures
        #================================================================

        # Calculate an array describing the x, y, z position of each actuator node
        # Note: The basic blade is oriented along the +y-axis
        self.blade_pos_base = np.vstack((np.zeros(self.num_blade_segments),
                                         self.rdim,
                                         np.zeros(self.num_blade_segments)))

        # Specify the velocity vector at each actuator node
        # Note: A blade with span oriented along the +y-axis moves in the +z direction
        self.blade_vel_base = np.vstack((np.zeros(self.num_blade_segments),
                                         np.zeros(self.num_blade_segments),
                                         np.linspace(0.0, self.tip_speed, self.num_blade_segments)))

        # Create unit vectors aligned with blade geometry
        # blade_unit_vec_base[:, 0] = points along rotor shaft
        # blade_unit_vec_base[:, 1] = points along blade span axis
        # blade_unit_vec_base[:, 2] = points tangential to blade span axis (generates a torque about rotor shaft)
        self.blade_unit_vec_base = np.array([[1.0, 0.0, 0.0],
                                             [0.0, 1.0, 0.0],
                                             [0.0, 0.0, 1.0]])

        #================================================================
        # Finally, initialize important dolfin terms
        #================================================================

        # Create a Constant "wrapper" to enable dolfin to track mpi_u_fluid
        self.mpi_u_fluid_constant = Constant(np.zeros(self.ndim*self.num_blades*self.num_blade_segments), name="mpi_u_fluid")


        # self.mchord.append(turb_i_chord)
        # self.mtwist.append(turb_i_twist)
        # self.mcl.append(turb_i_lift)
        # self.mcd.append(turb_i_drag)
        # self.chord = np.array(self.mchord,dtype=float)
        # self.cl = np.array(self.mcl,dtype=float)
        # self.cd = np.array(self.mcd,dtype=float)
        # self.farm.baseline_chord = np.array(self.chord[0])/self.chord_factor

        # self.cyld_expr_list = [None]*self.farm.numturbs

        # FIXME: need to get these coordinates the correct way
        # Make this a list of constants

        # self.mchord = Constant(self.chord, name="chord_{:d}".format(self.index))
        # self.mtwist = Constant(self.twist, name="twist_{:d}".format(self.index))
        # self.mlift = Constant(self.lift, name="lift_{:d}".format(self.index))
        # self.mdrag = Constant(self.drag, name="drag_{:d}".format(self.index))


    def init_lift_drag_lookup_tables(self):

        if self.read_turb_data:

            airfoil_data_path = 'airfoil_polars'

            # Determine the number of files in airfoil_data_path
            num_files = len(glob.glob('%s/*.txt' % (airfoil_data_path)))

            interp_radii = np.linspace(0.0, self.radius, num_files)

            for file_id in range(num_files):
                # print('Reading Airfoil Data #%d' % (file_id))
                data = np.genfromtxt('%s/af_station_%d.txt' % (airfoil_data_path, file_id), skip_header=1, delimiter=' ')

                if file_id == 0:
                    # If this is the first file, store the angle data
                    interp_angles = data[:, 0]
                    num_angles = np.size(interp_angles)
                    
                    # If this is the first file, allocate space for the tables        
                    lift_table = np.zeros((num_angles, num_files))
                    drag_table = np.zeros((num_angles, num_files))
                    
                # Store all the lift and drag data in the file_id column
                lift_table[:, file_id] = data[:, 1]
                drag_table[:, file_id] = data[:, 2]

            # Create interpolation functions for lift and drag based on angle of attack and location along blade
            self.lookup_cl = interp.RectBivariateSpline(interp_angles, interp_radii, lift_table)
            self.lookup_cd = interp.RectBivariateSpline(interp_angles, interp_radii, drag_table)

        else:
            self.lookup_cl = None
            self.lookup_cd = None

    def init_blade_properties(self):

        if self.read_turb_data:

            self.fprint('Setting chord, lift, and drag from file \'%s\'' % (self.read_turb_data))

            actual_turbine_data = np.genfromtxt(self.read_turb_data, delimiter = ',', skip_header = 1)

            actual_x = actual_turbine_data[:, 0]

            actual_chord = self.chord_factor*actual_turbine_data[:, 1]

            # Baseline twist is expressed in degrees, convert to radians
            actual_twist = actual_turbine_data[:, 2]/180.0*np.pi

            actual_cl = actual_turbine_data[:, 3]
            actual_cd = actual_turbine_data[:, 4]

            # Create interpolators for chord, lift, and drag
            inter_chord = interp.interp1d(actual_x, actual_chord)
            interp_twist = interp.interp1d(actual_x, actual_twist)
            interp_cl = interp.interp1d(actual_x, actual_cl)
            interp_cd = interp.interp1d(actual_x, actual_cd)

            # Construct the points at which to generate interpolated values
            interp_points = np.linspace(0.0, 1.0, self.num_blade_segments)

            # Generate the interpolated values
            chord = inter_chord(interp_points)
            twist = interp_twist(interp_points)

            # Note that this is not the lookup table for cl and cd based on AoA and radial
            # location along the blade, rather, it is the initialization based on a
            # 1D interpolation where AoA is assumed to be a few degrees set back from stall.
            # If using a lookup table which include AoA, these values will be overwritten 
            # during the course of the solve.
            cl = interp_cl(interp_points)
            cd = interp_cd(interp_points)

        else:
            # If not reading from a file, prescribe dummy values
            chord = self.radius/20.0*np.ones(self.num_blade_segments)
            twist = np.zeros(self.num_blade_segments)
            cl = np.ones(self.num_blade_segments)
            cd = 0.1*np.ones(self.num_blade_segments)

        # Store the chord, twist, cl, and cd values
        self.chord = chord
        self.twist = twist
        self.cl = cl
        self.cd = cd

        # Store a copy of the original values for future use
        self.baseline_chord = chord
        self.baseline_twist = twist
        self.baseline_cl = cl
        self.baseline_cd = cd

        self.max_chord = 1.5*np.amax(chord)


    def init_unsteady_alm_terms(self):

        self.rotor_torque = np.zeros(1)
        self.rotor_torque_count = np.zeros(1, dtype=int)
        # self.rotor_torque_dolfin = 0.0
        # self.tf.vector()[:] = 0.0

        # The forces should be imposed at the current position/time PLUS 0.5*dt
        simTime_ahead = self.simTime + 0.5*self.dt

        # The fluid velocity should be probed at the current position/time MINUS 0.5*dt
        if self.simTime_prev is None:
            simTime_behind = self.simTime
        else:
            simTime_behind = 0.5*(self.simTime_prev + self.simTime)

        self.theta_ahead = simTime_ahead*self.angular_velocity
        self.theta_behind = simTime_behind*self.angular_velocity


    def get_u_fluid_at_alm_nodes(self, u_k):

        # Create an empty array to hold all the components of velocity
        mpi_u_fluid = np.zeros(self.ndim*self.num_blades*self.num_blade_segments)
        mpi_u_fluid_count = np.zeros(self.ndim*self.num_blades*self.num_blade_segments)

        for blade_ct, theta_0 in enumerate(self.theta_vec):
            Rx = self.rot_x(self.theta_behind + theta_0)
            Rz = self.rot_z(float(self.myaw))

            # Rotate the blades into the correct angular position around the x-axis
            # and yaw this turbine around the z-axis
            blade_pos = np.dot(Rz, np.dot(Rx, self.blade_pos_base))

            # Get the position of this turbine and shift the blade positions there
            blade_pos[0, :] += float(self.mx)
            blade_pos[1, :] += float(self.my)
            blade_pos[2, :] += float(self.mz)

            # Need to probe the velocity point at each actuator node,
            # where actuator nodes are individual columns of blade_pos
            for k in range(self.num_blade_segments):
                # If using the local velocity, measure at the blade
                if self.use_local_velocity:
                    xi = blade_pos[0, k]
                else:
                    xi = self.dom.x_range[0]

                yi = blade_pos[1, k]
                zi = blade_pos[2, k]

                # Try to access the fluid velocity at this actuator point
                # If this rank doesn't own that point, an error will occur,
                # in which case zeros should be reported
                try:
                    fn_val = u_k(np.array([xi, yi, zi]))
                    start_pt = self.ndim*blade_ct*self.num_blade_segments + self.ndim*k
                    end_pt = start_pt + self.ndim
                    mpi_u_fluid[start_pt:end_pt] = fn_val
                    mpi_u_fluid_count[start_pt:end_pt] = [1, 1, 1]
                except:
                    pass

        data_in_fluid = np.zeros((self.params.num_procs, np.size(mpi_u_fluid)))
        self.params.comm.Gather(mpi_u_fluid, data_in_fluid, root=0)

        data_in_count = np.zeros((self.params.num_procs, np.size(mpi_u_fluid_count)))
        self.params.comm.Gather(mpi_u_fluid_count, data_in_count, root=0)

        if self.params.rank == 0:
            mpi_u_fluid_sum = np.sum(data_in_fluid, axis=0)
            mpi_u_fluid_count_sum = np.sum(data_in_count, axis=0)

            # This removes the possibility of a velocity shared between multiple nodes being reported
            # multiple times and being effectively doubled (or worse) when summing mpi_u_fluid across processes
            mpi_u_fluid = mpi_u_fluid_sum/mpi_u_fluid_count_sum

        self.params.comm.Bcast(mpi_u_fluid, root=0)

        # Populate the Constant "wrapper" with the velocity values to enable dolfin to track mpi_u_fluid
        self.mpi_u_fluid_constant.assign(Constant(mpi_u_fluid, name="mpi_u_fluid"))


    def compute_rotor_torque(self):

        data_in_torque = np.zeros(self.params.num_procs)
        self.params.comm.Gather(self.rotor_torque, data_in_torque, root=0)

        data_in_torque_count = np.zeros(self.params.num_procs, dtype=int)
        self.params.comm.Gather(self.rotor_torque_count, data_in_torque_count, root=0)

        if self.params.rank == 0:
            rotor_torque_sum = np.sum(data_in_torque)
            rotor_torque_count_sum = np.sum(data_in_torque_count)

            # This removes the possibility of a power being doubled or tripled
            # if multiple ranks include this turbine and therefore calculate a torque
            self.rotor_torque = rotor_torque_sum/rotor_torque_count_sum

        self.params.comm.Bcast(self.rotor_torque, root=0)


    def turbine_force(self, u, inflow_angle, fs, **kwargs):
        # if dfd is None, alm_output is a dolfin function (tf) [1 x numPts*ndim]
        # otherwise, it returns a numpy array of derivatives [numPts*ndim x numControls]

        try:
            self.simTime = kwargs['simTime']
            self.dt = kwargs['dt']
        except:
            raise ValueError('"simTime" and "dt" must be specified for the calculation of ALM force.')

        # If this is the first call to the function, set some things up before proceeding
        if self.first_call_to_alm:
            self.init_constant_alm_terms(fs)
            self.init_blade_properties()
            self.init_lift_drag_lookup_tables()
            self.create_controls(initial_call_from_setup=False)

        # Initialize summation, counting, etc., variables for alm solve
        self.init_unsteady_alm_terms()

        # Call the function to build the complete mpi_u_fluid array
        self.get_u_fluid_at_alm_nodes(u)

        # Call the ALM function for this turbine
        self.tf = self.build_actuator_lines(u, inflow_angle, fs)

        # Do some sharing of information when everything is finished
        self.compute_rotor_torque()

        # Store the most recent simTime for use in the next iteration
        self.simTime_prev = self.simTime

        if self.first_call_to_alm:
            self.first_call_to_alm = False

        return self.tf


    def power(self, u, inflow_angle):
        # Create a cylindrical expression aligned with the position of this turbine
        self.cyld_expr = Expression(('sin(yaw)*(x[2]-zs)', '-cos(yaw)*(x[2]-zs)', '(x[1]-ys)*cos(yaw)-(x[0]-xs)*sin(yaw)'),
            degree=1,
            yaw=self.myaw,
            xs=self.mx,
            ys=self.my,
            zs=self.mz)

        self.power_dolfin = assemble(dot(-self.tf*self.angular_velocity, self.cyld_expr)*dx)
        self.power_numpy = self.rotor_torque*self.angular_velocity

        # print("in turb.poweer()",self.power_dolfin, self.power_numpy)

        print('Error between dolfin and numpy: %e' % (float(self.power_dolfin) - self.power_numpy))

        return self.power_dolfin

    def prepare_saved_functions(self, func_list):
        pass