"""
The windfarm manager contains everything required to set up a 
windfarm.
"""

import __main__
import os

### Get the name of program importing this package ###
if hasattr(__main__,"__file__"):
    main_file = os.path.basename(__main__.__file__)
else:
    main_file = "ipython"
    
### This checks if we are just doing documentation ###
if not main_file in ["sphinx-build", "__main__.py"]:
    from dolfin import *
    import numpy as np
    from sys import platform
    import math
    import time
    import shutil, copy
    from scipy.special import gamma
    import scipy.interpolate as interp

    ### Import the cumulative parameters ###
    from windse import windse_parameters, BaseHeight, CalculateDiskTurbineForces, UpdateActuatorLineForce, RadialChordForce

    ### Check if we need dolfin_adjoint ###
    if windse_parameters.dolfin_adjoint:
        from dolfin_adjoint import *

    ### This import improves the plotter functionality on Mac ###
    if platform == 'darwin':
        import matplotlib
        matplotlib.use('TKAgg')
    import matplotlib.pyplot as plt

class GenericWindFarm(object):
    """
    A GenericProblem contains on the basic functions required by all problem objects.
    
    Args: 
        dom (:meth:`windse.DomainManager.GenericDomain`): a windse domain object.
    """
    def __init__(self, dom):
        ### save a reference of option and create local version specifically of domain options ###
        self.params = windse_parameters
        self.dom = dom
        self.rd_first_save = True
        self.fprint = self.params.fprint
        self.tag_output = self.params.tag_output
        self.debug_mode = self.params.debug_mode

        ### Init empty design variables ###
        self.cl = None;    self.mcl = None
        self.cd = None;    self.mcd = None
        self.chord = None; self.mchord = None
        self.x = None;     self.mx = None
        self.y = None;     self.my = None
        self.yaw = None;   self.myaw = None
        self.axial = None; self.maxial = None
        
        ### Init empty design variables ###
        self.cl = None;    self.mcl = None
        self.cd = None;    self.mcd = None
        self.chord = None; self.mchord = None
        self.x = None;     self.mx = None
        self.y = None;     self.my = None
        self.yaw = None;   self.myaw = None
        self.axial = None; self.maxial = None

        ### Update attributes based on params file ###
        for key, value in self.params["wind_farm"].items():
            if isinstance(value,list):
                setattr(self,key,np.array(value))
            else:
                setattr(self,key,value)

        ### Check if we need a 
        self.extra_kwarg = {}
        if self.params.dolfin_adjoint:
            self.extra_kwarg["annotate"] = False

        self.optimizing = False
        if self.params.performing_opt_calc:
            self.layout_bounds = self.params["optimization"]["layout_bounds"]
            self.control_types = self.params["optimization"]["control_types"]
            self.optimizing = True

    def DebugOutput(self):
        if self.debug_mode:
            self.tag_output("min_x", np.min(self.x))
            self.tag_output("max_x", np.max(self.x))
            self.tag_output("avg_x", np.mean(self.x))
            self.tag_output("min_y", np.min(self.y))
            self.tag_output("max_y", np.max(self.y))
            self.tag_output("avg_y", np.mean(self.y))
            self.tag_output("min_z", np.min(self.z))
            self.tag_output("max_z", np.max(self.z))
            self.tag_output("avg_z", np.mean(self.z))
            self.tag_output("min_yaw", np.min(self.yaw))
            self.tag_output("max_yaw", np.max(self.yaw))
            self.tag_output("avg_yaw", np.mean(self.yaw))
            # x, y, z, yaw, chord, 

    def PlotFarm(self,show=False,filename="wind_farm",power=None):
        """
        This function plots the locations of each wind turbine and
        saves the output to output/.../plots/

        :Keyword Arguments:
            * **show** (*bool*): Default: True, Set False to suppress output but still save.
        """
        if self.numturbs == 0:
            return

        ### Create the path names ###
        folder_string = self.params.folder+"/plots/"
        file_string = self.params.folder+"/plots/"+filename+".pdf"

        ### Check if folder exists ###
        if not os.path.exists(folder_string) and self.params.rank == 0: os.makedirs(folder_string)

        ### Create a list that outlines the extent of the farm ###
        if self.optimizing and "layout" in self.control_types and self.layout_bounds != "wind_farm":
            ex_list_x = [self.layout_bounds[0][0],self.layout_bounds[0][1],self.layout_bounds[0][1],self.layout_bounds[0][0],self.layout_bounds[0][0]]
            ex_list_y = [self.layout_bounds[1][0],self.layout_bounds[1][0],self.layout_bounds[1][1],self.layout_bounds[1][1],self.layout_bounds[1][0]]
        else:
            ex_list_x = [self.ex_x[0],self.ex_x[1],self.ex_x[1],self.ex_x[0],self.ex_x[0]]
            ex_list_y = [self.ex_y[0],self.ex_y[0],self.ex_y[1],self.ex_y[1],self.ex_y[0]]

        ### Generate and Save Plot ###
        fig, ax = plt.subplots()
        if hasattr(self.dom,"boundary_line"):
            ax.plot(*self.dom.boundary_line/self.dom.xscale,c="k")
        ax.plot(np.array(ex_list_x)/self.dom.xscale, np.array(ex_list_y)/self.dom.xscale,c="r")

        ### Plot Blades
        for i in range(self.numturbs):
            blade_n = [np.cos(self.yaw[i]),np.sin(self.yaw[i])]
            rr = self.RD[i]/2.0
            blade_x = np.array([self.x[i]+rr*blade_n[1],self.x[i]-rr*blade_n[1]])/self.dom.xscale
            blade_y = np.array([self.y[i]-rr*blade_n[0],self.y[i]+rr*blade_n[0]])/self.dom.xscale
            ax.plot(blade_x,blade_y,c='k',linewidth=2,zorder=1)

        ### Choose coloring for the turbines ###
        if isinstance(power,(list,np.ndarray)):
            coloring = power
        else:
            coloring = np.array(self.z)/self.dom.xscale

        ### Plot Hub Locations
        p=ax.scatter(self.x/self.dom.xscale,self.y/self.dom.xscale,c=coloring,cmap="coolwarm",edgecolors=(0, 0, 0, 1),s=20,zorder=2)
        # p=plt.scatter(self.x,self.y,c="k",s=70)
        plt.xlim(self.dom.x_range[0]/self.dom.xscale,self.dom.x_range[1]/self.dom.xscale)
        plt.ylim(self.dom.y_range[0]/self.dom.xscale,self.dom.y_range[1]/self.dom.xscale)
        clb = plt.colorbar(p)
        clb.ax.set_ylabel('Hub Elevation')

        ### Annotate ###
        for i in range(self.numturbs):
            ax.annotate(i, (self.x[i]/self.dom.xscale,self.y[i]/self.dom.xscale),(5,0),textcoords='offset pixels')

        if power is None:
            plt.title("Location of the Turbines")
        elif isinstance(power,(list,np.ndarray)):
            plt.title("Objective Value: {: 5.6f}".format(sum(power)))
        else:
            plt.title("Objective Value: {: 5.6f}".format(power))

        plt.savefig(file_string, transparent=True)

        if show:
            plt.show()

        plt.close()

    def PlotChord(self,show=False,filename="chord_profiles",power=None, bounds=None):

        ### Create the path names ###
        folder_string = self.params.folder+"/plots/"
        file_string = self.params.folder+"/plots/"+filename+".pdf"

        ### Check if folder exists ###
        if not os.path.exists(folder_string) and self.params.rank == 0: os.makedirs(folder_string)

        ### Calculate x values ###
        x = np.linspace(0,1,self.blade_segments)

        ### Plot Chords ###
        plt.figure()
        plt.plot(x,self.baseline_chord,label="baseline",c="k")
        if bounds is None:
            lower=[]
            upper=[]
            c_avg = 0
            for k, seg_chord in enumerate(self.baseline_chord):
                    modifier = 2.0
                    max_chord = self.max_chord
                    lower.append(seg_chord/modifier)
                    upper.append(max(min(seg_chord*modifier,max_chord),c_avg))
                    c_avg = (c_avg*k+seg_chord)/(k+1)
            plt.plot(x,lower,"--r",label="Optimization Boundaries")
            plt.plot(x,upper,"--r")
        else:
            plt.plot(x,bounds[0][-self.blade_segments:],"--r",label="Optimization Boundaries")
            plt.plot(x,bounds[1][-self.blade_segments:],"--r")

        for i in range(self.numturbs):
            y = np.array(self.chord[i],dtype=float)
            plt.plot(x,y,'.-',label=i)

        plt.xlim(0,1)
        if power is None:
            plt.title("Chord along blade span")
        elif isinstance(power,(list,np.ndarray)):
            plt.title("Objective Value: {: 5.6f}".format(sum(power)))
        else:
            plt.title("Objective Value: {: 5.6f}".format(power)) 
        plt.xlabel("Blade Span")      
        plt.ylabel("Chord")
        plt.legend()      

        plt.savefig(file_string, transparent=True)

        if show:
            plt.show()

        plt.close()

    def SaveWindFarm(self,val=None,filename="wind_farm"):

        ### Create the path names ###
        folder_string = self.params.folder+"/data/"
        if val is not None:
            file_string = self.params.folder+"/data/"+filename+"_"+repr(val)+".txt"
        else:
            file_string = self.params.folder+"/data/"+filename+".txt"

        ### Check if folder exists ###
        if not os.path.exists(folder_string) and self.params.rank == 0: os.makedirs(folder_string)

        ### Define the header string ###
        head_str="#    x    y    HH    Yaw    Diameter    Thickness    Axial_Induction"


        ### Save text file ###
        Sx = self.dom.xscale
        output = np.array([self.x/Sx, self.y/Sx, self.HH/Sx, self.yaw, self.RD/Sx, self.thickness/Sx, self.axial])
        np.savetxt(file_string,output.T,header=head_str)

    def SaveALMData(self):
        pass


    def SaveActuatorDisks(self,val=0):
        """
        This function saves the turbine force if exists to output/.../functions/
        """

        self.dom.mesh.coordinates()[:]=self.dom.mesh.coordinates()[:]/self.dom.xscale
        if hasattr(self.actuator_disks,"_cpp_object"):
            if self.rd_first_save:
                self.rd_file = self.params.Save(self.actuator_disks,"actuator_disks",subfolder="functions/",val=val)
                self.rd_first_save = False
            else:
                self.params.Save(self.actuator_disks,"actuator_disks",subfolder="functions/",val=val,file=self.rd_file)

        self.dom.mesh.coordinates()[:]=self.dom.mesh.coordinates()[:]*self.dom.xscale

    def CalculateFarmBoundingBox(self):
        """
        This functions takes into consideration the turbine locations, diameters, 
        and hub heights to create lists that describe the extent of the windfarm.
        These lists are append to the parameters object.
        """
        ### Locate the extreme turbines ### 
        x_min = np.argmin(self.x)
        x_max = np.argmax(self.x)
        y_min = np.argmin(self.y)
        y_max = np.argmax(self.y)
        z_min = np.argmin(self.z)
        z_max = np.argmax(self.z)

        ### Calculate the extent of the farm ###
        self.ex_x = [self.x[x_min]-self.RD[x_min]/2.0,self.x[x_max]+self.RD[x_max]/2.0]
        self.ex_y = [self.y[y_min]-self.RD[y_min]/2.0,self.y[y_max]+self.RD[y_max]/2.0]
        self.ex_z = [min(self.ground),self.z[z_max]+self.RD[z_max]/2.0]

        ### Update the options ###
        self.params["wind_farm"]["ex_x"] = self.ex_x
        self.params["wind_farm"]["ex_y"] = self.ex_y
        self.params["wind_farm"]["ex_z"] = self.ex_z
        
        return [self.ex_x,self.ex_y,self.ex_z]

    def CreateConstants(self):
        """
        This functions converts lists of locations and axial inductions
        into dolfin.Constants. This is useful in optimization.
        """
        self.mx = []
        self.my = []
        self.ma = []
        self.myaw = []
        for i in range(self.numturbs):
            self.mx.append(Constant(self.x[i]))
            self.my.append(Constant(self.y[i]))
            self.ma.append(Constant(self.axial[i]))
            self.myaw.append(Constant(self.yaw[i]))

        for i in range(self.numturbs):
            self.mx[i].rename("x"+repr(i),"x"+repr(i))
            self.my[i].rename("y"+repr(i),"y"+repr(i))
            self.myaw[i].rename("yaw"+repr(i),"yaw"+repr(i))
            self.ma[i].rename("a"+repr(i),"a"+repr(i))

    def UpdateControls(self,x=None,y=None,yaw=None,a=None,chord=None):

        if x is not None:
            self.x = np.array(x,dtype=float)
        if y is not None:
            self.y = np.array(y,dtype=float)
        if yaw is not None:
            self.yaw = np.array(yaw,dtype=float)
        if a is not None:
            self.axial = np.array(a,dtype=float)


        if chord is not None:
            chord = np.array(chord, dtype = float)
            self.chord[turb_index] = chord
            for k in range(self.num_blade_segments):
                self.mchord[turb_index][k] = Constant(chord[k])


        for i in range(self.numturbs):
            self.mx[i] = Constant(self.x[i])
            self.my[i] = Constant(self.y[i])
            self.ma[i] = Constant(self.axial[i])
            self.myaw[i] = Constant(self.yaw[i])
            # if self.analytic:
            #     self.mz[i] = self.dom.Ground(self.mx[i],self.my[i])+float(self.HH[i])
            # else:
            self.mz[i] = BaseHeight(self.mx[i],self.my[i],self.dom.Ground)+float(self.HH[i])
            self.z[i] = float(self.mz[i])
            self.ground[i] = self.z[i] - self.HH[i]

    def SimpleControlUpdate(self):
        for i in range(self.numturbs):

            # Update per turbine controls
            self.mx[i] = Constant(self.x[i])
            self.my[i] = Constant(self.y[i])
            self.ma[i] = Constant(self.axial[i])
            self.myaw[i] = Constant(self.yaw[i])

            # Update ground stuff
            self.mz[i] = BaseHeight(self.mx[i],self.my[i],self.dom.Ground)+float(self.HH[i])
            self.z[i] = float(self.mz[i])
            self.ground[i] = self.z[i] - self.HH[i]       

            # Update blade level controls
            if self.turbine_method == "alm" or self.force == "chord": 
                for k in range(self.num_blade_segments):
                    self.mcl[i][k] = Constant(self.cl[i][k])
                    self.mcd[i][k] = Constant(self.cd[i][k])
                    self.mchord[i][k] = Constant(self.chord[i][k])



    def CreateLists(self):
        """
        This function creates lists from single values. This is useful
        when the params.yaml file defines only one type of turbine.
        """
        for prop in ["HH", "RD", "thickness", "radius", "yaw", "axial"]:
            val = getattr(self,prop)
            if np.isscalar(val):
                setattr(self,prop,np.full(self.numturbs,val))

    def CalculateHeights(self):
        """
        This function calculates the absolute heights of each turbine.
        """
        self.mz = [] 
        self.z = np.zeros(self.numturbs)
        self.ground = np.zeros(self.numturbs)
        for i in range(self.numturbs):
            # if self.analytic:
            #     self.mz.append(self.dom.Ground(self.mx[i],self.my[i])+float(self.HH[i]))
            # else:
            self.mz.append(BaseHeight(self.mx[i],self.my[i],self.dom.Ground)+float(self.HH[i]))
            self.z[i] = float(self.mz[i])
            self.ground[i] = self.z[i] - self.HH[i]




    def SimpleRefine(self,radius,expand_factor=1):
        if self.numturbs == 0:
            return

        self.fprint("Cylinder Refinement Near Turbines",special="header")
        refine_start = time.time()

        ### Calculate expanded values ###
        radius = expand_factor*radius

        ### Create the cell markers ###
        cell_f = MeshFunction('bool', self.dom.mesh, self.dom.mesh.geometry().dim(),False)
        
        ### Get Dimension ###
        n = self.numturbs
        d = self.dom.dim

        ### Get Turbine Coordinates ###
        turb_x = np.array(self.x)
        turb_y = np.array(self.y)
        if self.dom.dim == 3:
            turb_z0 = self.dom.z_range[0]-radius
            turb_z1 = self.z+radius

        self.fprint("Marking Near Turbine")
        mark_start = time.time()
        for cell in cells(self.dom.mesh):
            ### Get Points of all cell vertices ##
            pt = cell.get_vertex_coordinates()
            x = pt[0::d]
            y = pt[1::d]
            if d == 3:
                z = pt[2::d]

            ### Find the minimum distance for each turbine with the vertices ###
            x_diff = np.power(np.subtract.outer(x,turb_x),2.0)
            y_diff = np.power(np.subtract.outer(y,turb_y),2.0)
            min_r = np.min(x_diff+y_diff,axis=0)

            ### Determine if cell is in radius for each turbine ###
            in_circle = min_r <= radius**2.0

            ### Determine if in cylinder ###
            if d == 3:
                in_z = np.logical_and(turb_z0 <= max(z), turb_z1 >= min(z))
                near_turbine = np.logical_and(in_circle, in_z)
            else:
                near_turbine = in_circle

            ### mark if cell is near any cylinder ###
            if any(near_turbine):
                cell_f[cell] = True

        mark_stop = time.time()
        self.fprint("Marking Finished: {:1.2f} s".format(mark_stop-mark_start))

        ### Refine Mesh ###
        self.dom.Refine(cell_f)

        ### Recompute Heights with new mesh ###
        self.CalculateHeights()

        refine_stop = time.time()
        self.fprint("Mesh Refinement Finished: {:1.2f} s".format(refine_stop-refine_start),special="footer")


    def WakeRefine(self,radius,length,theta=0.0,expand_factor=1,centered=False):
        if self.numturbs == 0:
            return

        self.fprint("Wake Refinement Near Turbines",special="header")
        refine_start = time.time()

        ### Calculate expanded values ###
        radius = expand_factor*radius/2.0
        length = length+2*(expand_factor-1)*radius

        ### Create the cell markers ###
        cell_f = MeshFunction('bool', self.dom.mesh, self.dom.mesh.geometry().dim(),False)

        ### Get Dimension ###
        n = self.numturbs
        d = self.dom.dim

        ### Get Turbine Coordinates ###
        turb_x = np.array(self.x)
        turb_y = np.array(self.y)
        if self.dom.dim == 3:
            turb_z = np.array(self.z)

        self.fprint("Marking Near Turbine")
        mark_start = time.time()
        for cell in cells(self.dom.mesh):
            ### Get Points of all cell vertices ##
            pt = cell.get_vertex_coordinates()
            x = pt[0::d]
            y = pt[1::d]
            if d == 3:
                z = pt[2::d]

            ### Rotate the Cylinder about the turbine axis ###
            x_diff = np.subtract.outer(x,turb_x)
            y_diff = np.subtract.outer(y,turb_y)
            x = (np.cos(theta)*(x_diff)-np.sin(theta)*(y_diff) + turb_x)
            y = (np.sin(theta)*(x_diff)+np.cos(theta)*(y_diff) + turb_y)

            ### Determine if in wake ###
            if centered:
                # Center the refinement region around the turbine
                # upstream and downstream by length/2
                x0 = turb_x - length/2.0
                x1 = turb_x + length/2.0
            else:
                # Otherwise, refine the default amount upstream (R)
                # and the full length amount downstreeam
                x0 = turb_x - radius
                x1 = turb_x + length

            in_wake = np.logical_and(np.greater(x,x0),np.less(x,x1))
            in_wake = np.any(in_wake,axis=0)

            ### Find the minimum distance for each turbine with the vertices ###
            y_diff = y-turb_y
            if d == 3:
                z_diff = np.subtract.outer(z,turb_z)
                min_r = np.min(np.power(y_diff,2.0)+np.power(z_diff,2.0),axis=0)
            else:
                min_r = np.min(np.power(y_diff,2.0),axis=0)

            ### Determine if cell is in radius for each turbine ###
            in_circle = min_r <= radius**2.0
            near_turbine = np.logical_and(in_circle, in_wake)

            ### mark if cell is near any cylinder ###
            if any(near_turbine):
                cell_f[cell] = True


        mark_stop = time.time()
        self.fprint("Marking Finished: {:1.2f} s".format(mark_stop-mark_start))

        ### Refine Mesh ###
        self.dom.Refine(cell_f)

        ### Recompute Heights with new mesh ###
        self.CalculateHeights()

        refine_stop = time.time()
        self.fprint("Mesh Refinement Finished: {:1.2f} s".format(refine_stop-refine_start),special="footer")

    def TearRefine(self,radius,theta=0.0,expand_factor=1):
        if self.numturbs == 0:
            return

        self.fprint("Tear Drop Refinement Near Turbines",special="header")
        refine_start = time.time()

        ### Calculate expanded values ###
        radius = expand_factor*radius

        ### Create the cell markers ###
        cell_f = MeshFunction('bool', self.dom.mesh, self.dom.mesh.geometry().dim(),False)
        
        ### Get Dimension ###
        n = self.numturbs
        d = self.dom.dim

        ### Get Turbine Coordinates ###
        turb_x = np.array(self.x)
        turb_y = np.array(self.y)
        if self.dom.dim == 3:
            turb_z0 = self.dom.z_range[0]-radius
            turb_z1 = self.z+radius

        self.fprint("Marking Near Turbine")
        mark_start = time.time()
        for cell in cells(self.dom.mesh):
            ### Get Points of all cell vertices ##
            pt = cell.get_vertex_coordinates()
            x = pt[0::d]
            y = pt[1::d]
            if d == 3:
                z = pt[2::d]

            ### Rotate the Cylinder about the turbine axis ###
            x_diff = np.subtract.outer(x,turb_x)
            y_diff = np.subtract.outer(y,turb_y)
            x = (np.cos(theta)*(x_diff)-np.sin(theta)*(y_diff) + turb_x)
            y = (np.sin(theta)*(x_diff)+np.cos(theta)*(y_diff) + turb_y)
            x_diff = x - turb_x
            y_diff = y - turb_y

            ### Find Closest Turbine ###
            min_dist = np.min(np.power(x_diff,2.0)+np.power(y_diff,2.0),axis=0)
            min_turb_id = np.argmin(min_dist)

            # ### Do something based on upstream or downstream ###
            # if min(x[:,min_turb_id]-turb_x[min_turb_id]) <= 0:
            #     val = -min_turb_id-1
            # else:
            #     val = min_turb_id+1

            # ### Determine if in z_range ###
            # if d == 3:
            #     in_z = turb_z0 <= max(z) and turb_z1[min_turb_id] >= min(z)
            #     if in_z:
            #         near_turbine = val
            #     else:
            #         near_turbine = 0
            # else:
            #     near_turbine = val

            ### Check if upstream or downstream and adjust accordingly ###
            cl_x = turb_x[min_turb_id]
            cl_y = turb_y[min_turb_id]
            dx = min(x[:,min_turb_id]-cl_x)
            dy = min(y[:,min_turb_id]-cl_y)
            if dx <= 0:
                dist = (dx*1.5)**2 + dy**2
            else:
                dist = (dx/2)**2 + dy**2

            ### determine if in z-range ###
            if d == 3:
                in_z = turb_z0 <= max(z) and turb_z1[min_turb_id] >= min(z)
                near_turbine = in_z and dist <= radius**2
            else:
                near_turbine = dist <= radius**2
            ### mark if cell is near any cylinder ###
            if near_turbine:
                cell_f[cell] = True


        # File("test.pvd") << cell_f
        # exit()

        mark_stop = time.time()
        self.fprint("Marking Finished: {:1.2f} s".format(mark_stop-mark_start))

        ### Refine Mesh ###
        self.dom.Refine(cell_f)

        ### Recompute Heights with new mesh ###
        self.CalculateHeights()

        refine_stop = time.time()
        self.fprint("Mesh Refinement Finished: {:1.2f} s".format(refine_stop-refine_start),special="footer")

    def SphereRefine(self,radius,expand_factor=1):
        if self.numturbs == 0:
            return

        self.fprint("Sphere Refinement Near Turbines",special="header")
        refine_start = time.time()

        ### Calculate expanded values ###
        radius = expand_factor*radius

        ### Create the cell markers ###
        cell_f = MeshFunction('bool', self.dom.mesh, self.dom.mesh.geometry().dim(),False)
        
        ### Get Dimension ###
        n = self.numturbs
        d = self.dom.dim

        ### Get Turbine Coordinates ###
        turb_x = np.array(self.x)
        turb_y = np.array(self.y)
        if self.dom.dim == 3:
            turb_z = np.array(self.z)
            

        self.fprint("Marking Near Turbine")
        mark_start = time.time()
        for cell in cells(self.dom.mesh):
            ### Get Points of all cell vertices ##
            pt = cell.get_vertex_coordinates()
            x = pt[0::d]
            y = pt[1::d]
            if d == 3:
                z = pt[2::d]

            ### Find the minimum distance for each turbine with the vertices ###
            min_r  = np.power(np.subtract.outer(x,turb_x),2.0)
            min_r += np.power(np.subtract.outer(y,turb_y),2.0)
            if d == 3:
                min_r += np.power(np.subtract.outer(z,turb_z),2.0)
            min_r = np.min(min_r,axis=0)

            ### Determine if cell is in radius for each turbine ###
            in_sphere = min_r <= radius**2.0

            ### mark if cell is near any cylinder ###
            if any(in_sphere):
                cell_f[cell] = True

        mark_stop = time.time()
        self.fprint("Marking Finished: {:1.2f} s".format(mark_stop-mark_start))

        ### Refine Mesh ###
        self.dom.Refine(cell_f)

        ### Recompute Heights with new mesh ###
        self.CalculateHeights()

        refine_stop = time.time()
        self.fprint("Mesh Refinement Finished: {:1.2f} s".format(refine_stop-refine_start),special="footer")

















    # def RefineTurbines(self,num,radius_multiplyer):

    #     self.fprint("Refining Near Turbines",special="header")
    #     mark_start = time.time()

    #     for i in range(num):
    #         if num>1:
    #             step_start = time.time()
    #             self.fprint("Refining Mesh Step {:d} of {:d}".format(i+1,num), special="header")

    #         cell_f = MeshFunction('bool', self.dom.mesh, self.dom.mesh.geometry().dim(),False)


    #         expand_turbine_radius = True

    #         if expand_turbine_radius:
    #             radius = (num-i)*radius_multiplyer*np.array(self.RD)/2.0
    #         else:
    #             radius = radius_multiplyer*np.array(self.RD)/2.0


    #         if self.dom.dim == 3:
    #             turb_x = np.array(self.x)
    #             turb_x = np.tile(turb_x,(4,1)).T
    #             turb_y = np.array(self.y)
    #             turb_y = np.tile(turb_y,(4,1)).T
    #             turb_z0 = self.dom.z_range[0]-radius
    #             turb_z1 = self.z+radius
    #         else:
    #             turb_x = np.array(self.x)
    #             turb_x = np.tile(turb_x,(3,1)).T
    #             turb_y = np.array(self.y)
    #             turb_y = np.tile(turb_y,(3,1)).T
    #         n = self.numturbs

    #         self.fprint("Marking Near Turbine")
    #         for cell in cells(self.dom.mesh):

    #             pt = cell.get_vertex_coordinates()
    #             if self.dom.dim == 3:
    #                 x = pt[0:-2:3]
    #                 x = np.tile(x,(n,1))
    #                 y = pt[1:-1:3]
    #                 y = np.tile(y,(n,1))
    #                 z = pt[2::3]
    #             else:
    #                 x = pt[0:-1:2]
    #                 x = np.tile(x,(n,1))
    #                 y = pt[1::2]
    #                 y = np.tile(y,(n,1))

    #             ### For each turbine, find which vertex is closet using squared distance
    #             force_cylindrical_refinement = True
                
    #             if force_cylindrical_refinement:
    #                 d_y = pt[1]
    #                 d_z = pt[2] - self.HH[0]
    #                 min_r = d_y**2 + d_z**2
    #             else:
    #                 min_r = np.min(np.power(turb_x-x,2.0)+np.power(turb_y-y,2.0),axis=1)

    #             downstream_teardrop_shape = False

    #             if downstream_teardrop_shape:
    #                 min_arg = np.argmin(np.power(turb_x-x,2.0)+np.power(turb_y-y,2.0),axis=1)
    #                 min_arg = np.argmin(min_arg)

    #                 if np.any(turb_x[min_arg] < x):
    #                     min_r = np.min(np.power(turb_x-x/2.0,2.0)+np.power(turb_y-y,2.0),axis=1)
    #                 else:
    #                     min_r = np.min(np.power(turb_x-x*2.0,2.0)+np.power(turb_y-y,2.0),axis=1)


    #             in_circle = min_r <= radius**2.0
    #             if self.dom.dim == 3:
    #                 if force_cylindrical_refinement:
    #                     in_z = -radius < pt[0]
    #                 else:
    #                     in_z = np.logical_and(turb_z0 <= max(z), turb_z1 >= min(z))
    #                 near_turbine = np.logical_and(in_circle, in_z)
    #             else:
    #                 near_turbine = in_circle

    #             if any(near_turbine):
    #                 cell_f[cell] = True
    #         mark_stop = time.time()
    #         self.fprint("Marking Finished: {:1.2f} s".format(mark_stop-mark_start))

    #         self.dom.Refine(1,cell_markers=cell_f)

    #         if num>1:
    #             step_stop = time.time()
    #             self.fprint("Step {:d} of {:d} Finished: {:1.2f} s".format(i+1,num,step_stop-step_start), special="footer")

    #     self.CalculateHeights()
    #     self.fprint("Turbine Refinement Finished",special="footer")

    def YawTurbine(self,x,x0,yaw):
        """
        This function yaws the turbines when creating the turbine force.

        Args:
            x (dolfin.SpatialCoordinate): the space variable, x
            x0 (list): the location of the turbine to be yawed
            yaw (float): the yaw value in radians
        """
        xrot =   cos(yaw)*(x[0]-x0[0]) + sin(yaw)*(x[1]-x0[1])
        yrot = - sin(yaw)*(x[0]-x0[0]) + cos(yaw)*(x[1]-x0[1])
        if self.dom.dim == 3:
            zrot = x[2]-x0[2]
        else:
            zrot = 0.0
        
        return [xrot,yrot,zrot]

    def NumpyTurbineForce(self,fs,mesh,inflow_angle=0.0):
        tf_start = time.time()
        self.fprint("Calculating Turbine Force",special="header")
        self.fprint("Using a Numpy Representation")

        self.inflow_angle = inflow_angle
        x = fs.tf_V0.tabulate_dof_coordinates().T
        [tf1, tf2, tf3], sparse_ids, actuator_array = CalculateDiskTurbineForces(x, self, fs, save_actuators=True)

        self.fprint("Turbine Force Space:  {}".format(fs.turbine_space))
        self.fprint("Turbine Force Degree: {:d}".format(fs.turbine_degree))
        self.fprint("Quadrature DOFS:      {:d}".format(fs.tf_V.dim()))
        self.fprint("Turbine DOFs:         {:d}".format(len(sparse_ids)))
        self.fprint("Compression:          {:1.4f} %".format(len(sparse_ids)/fs.tf_V.dim()*100))

        ### Rename for Identification ###
        tf1.rename("tf1","tf1")
        tf2.rename("tf2","tf2")
        tf3.rename("tf3","tf3")

        ### Construct the actuator disks for post processing ###
        # self.actuator_disks_list = actuator_disks
        self.actuator_disks = Function(fs.tf_V)
        self.actuator_disks.vector()[:] = np.sum(actuator_array,axis=1)
        self.fprint("Projecting Turbine Force")
        self.actuator_disks = project(self.actuator_disks,fs.V,solver_type='mumps',form_compiler_parameters={'quadrature_degree': fs.turbine_degree},**self.extra_kwarg)
        
        self.actuator_disks_list = []
        for i in range(self.numturbs):
            temp = Function(fs.tf_V)
            temp.vector()[:] = np.array(actuator_array[:,i])
            self.actuator_disks_list.append(temp)

        tf_stop = time.time()
        self.fprint("Turbine Force Calculated: {:1.2f} s".format(tf_stop-tf_start),special="footer")
        return (tf1, tf2, tf3)

    def DolfinTurbineForce(self,fs,mesh,inflow_angle=0.0):
        """
        This function creates a turbine force by applying 
        a spacial kernel to each turbine. This kernel is 
        created from the turbines location, yaw, thickness, diameter,
        and force density. Currently, force density is limit to a scaled
        version of 

        .. math::

            r\\sin(r),

        where :math:`r` is the distance from the center of the turbine.

        Args:
            V (dolfin.FunctionSpace): The function space the turbine force will use.
            mesh (dolfin.mesh): The mesh

        Returns:
            tf (dolfin.Function): the turbine force.

        Todo:
            * Setup a way to get the force density from file
        """
        tf_start = time.time()
        self.fprint("Calculating Turbine Force",special="header")
        self.fprint("Using a Dolfin Representation")

        ### this section of code is a hack to get "chord"-type disk representation ###
        if self.mchord is not None:
            if self.chord is not None:
                if self.blade_segments == "computed":
                    self.num_blade_segments = 10 ##### FIX THIS ####
                    self.blade_segments = self.num_blade_segments
                else:
                    self.num_blade_segments = self.blade_segments

                if self.read_turb_data:
                    print('Num blade segments: ', self.num_blade_segments)
                    turb_data = self.params["wind_farm"]["read_turb_data"]
                    self.fprint('Setting chord from file \'%s\'' % (turb_data))
                    actual_turbine_data = np.genfromtxt(turb_data, delimiter = ',', skip_header = 1)
                    actual_x = actual_turbine_data[:, 0]
                    actual_chord = self.chord_factor*actual_turbine_data[:, 1]
                    chord_interp = interp.interp1d(actual_x, actual_chord)
                    interp_points = np.linspace(0.0, 1.0, self.blade_segments)
                    # Generate the interpolated values
                    self.chord = chord_interp(interp_points)
                else:
                    self.chord = np.ones(self.blade_segments)
            self.num_blade_segments = self.blade_segments
            self.baseline_chord = copy.copy(self.chord)

            self.cl = np.ones(self.blade_segments)
            self.cd = np.ones(self.blade_segments)
            self.mcl = []
            self.mcd = []
            self.mchord = []
            for i in range(self.numturbs):
                self.mcl.append([])
                self.mcd.append([])
                self.mchord.append([])
                for j in range(self.blade_segments):
                    self.mcl[i].append(Constant(self.cl[j]))
                    self.mcd[i].append(Constant(self.cd[j]))
                    self.mchord[i].append(Constant(self.chord[j]))
            self.cl = np.array(self.mcl,dtype=float)
            self.cd = np.array(self.mcd,dtype=float)
            self.chord = np.array(self.mchord,dtype=float)





        x=SpatialCoordinate(mesh)
        tf=0
        rd=0
        tf1=0
        tf2=0
        tf3=0
        self.actuator_disks_list = []
        for i in range(self.numturbs):
            x0 = [self.mx[i],self.my[i],self.mz[i]]
            yaw = self.myaw[i]+inflow_angle
            W = self.thickness[i]*1.0
            R = self.RD[i]/2.0
            ma = self.ma[i]
            C_tprime = 4*ma/(1-ma)

            ### Set up some dim dependent values ###
            S_norm = (2.0+pi)/(2.0*pi)
            T_norm = 2.0*gamma(7.0/6.0)
            if self.dom.dim == 3:
                WTGbase = as_vector((cos(yaw),sin(yaw),0.0))
                A = pi*R**2.0 
                D_norm = pi*gamma(4.0/3.0)
            else:
                WTGbase = as_vector((cos(yaw),sin(yaw)))
                A = 2*R 
                D_norm = 2.0*gamma(7.0/6.0)

            ### Rotate and Shift the Turbine ###
            xs = self.YawTurbine(x,x0,yaw)

            ### Create the function that represents the Thickness of the turbine ###
            T = exp(-pow((xs[0]/W),6.0))

            ### Create the function that represents the Disk of the turbine
            r = sqrt(xs[1]**2.0+xs[2]**2.0)/R
            D = exp(-pow(r,6.0))

            ### Create the function that represents the force ###
            if self.force == "constant":
                force = 1.0
            elif self.force == "sine":
                force = (r*sin(pi*r)+0.5)/S_norm
            elif self.force == "chord":
                chord = self.mchord[i]
                force = RadialChordForce(r,chord)
            F = -0.5*A*C_tprime*force

            ### Calculate normalization constant ###
            volNormalization = T_norm*D_norm*W*R**(self.dom.dim-1)
            # volNormalization_a = assemble(T*D*dx)
            # print(volNormalization_a,volNormalization)#,volNormalization/(W*R**(self.dom.dim-1)),T_norm*D_norm)

            # compute disk averaged velocity in yawed case and don't project
            self.actuator_disks_list.append(F*T*D*WTGbase/volNormalization)
            rd  += F*T*D*WTGbase/volNormalization
            tf1 += F*T*D*WTGbase/volNormalization * cos(yaw)**2
            tf2 += F*T*D*WTGbase/volNormalization * sin(yaw)**2
            tf3 += F*T*D*WTGbase/volNormalization * 2.0 * cos(yaw) * sin(yaw)

        ### Save the actuator disks for post processing ###
        self.fprint("Projecting Turbine Force")
        self.actuator_disks = project(rd,fs.V,solver_type='cg',**self.extra_kwarg)
        # self.actuator_disks = project(rd,fs.V,solver_type='mumps',**self.extra_kwarg)

        tf_stop = time.time()
        self.fprint("Turbine Force Calculated: {:1.2f} s".format(tf_stop-tf_start),special="footer")
        return (tf1, tf2, tf3)


    def CalculateActuatorLineTurbineForces(self, problem, simTime, dfd=None, verbose=False):
        # if dfd is None, alm_output is a dolfin function (tf) [1 x numPts*ndim]
        # otherwise, it returns a numpy array of derivatives [numPts*ndim x numControls]

        # for all turbs:
        #     tf, tf_ind = BuildSingleALM(problem, simTime, dfd, k)

        def rot_x(theta):
            Rx = np.array([[1, 0, 0],
                           [0, np.cos(theta), -np.sin(theta)],
                           [0, np.sin(theta), np.cos(theta)]])

            return Rx

        def rot_y(theta):
            Ry = np.array([[np.cos(theta), 0, np.sin(theta)],
                           [0, 1, 0],
                           [-np.sin(theta), 0, np.cos(theta)]])
            
            return Ry

        def rot_z(theta):
            Rz = np.array([[np.cos(theta), -np.sin(theta), 0],
                           [np.sin(theta), np.cos(theta), 0],
                           [0, 0, 1]])
            
            return Rz

        # ================================================================

        def init_constant_alm_terms(problem):

            # Create unit-length blade 1, oriented along the positive y-axis
            blade_1_pos = np.vstack((np.zeros(problem.num_blade_segments),
                                     np.linspace(0.0, 1.0, problem.num_blade_segments),
                                     np.zeros(problem.num_blade_segments)))


            # Create unit-length blade 2, rotated 120* around the x-axis
            theta_2 = 120.0/180.0*np.pi
            blade_2_pos = np.dot(rot_x(theta_2), blade_1_pos)

            # Create unit-length blade 3, rotated 240* around the x-axis
            theta_3 = 240.0/180.0*np.pi
            blade_3_pos = np.dot(rot_x(theta_3), blade_1_pos)

            # Combine all the blades into a single array, dim = [3, num_blade_segments*3]
            # This should be shared with updateActuatorLineForce
            problem.blade_pos_base = np.hstack((blade_1_pos, blade_2_pos, blade_3_pos))

            # Get the coordinates of the vector function space
            coords = problem.fs.V.tabulate_dof_coordinates()
            coords = np.copy(coords[0::problem.dom.dim, :])

            problem.coords = coords

            # Resape a linear copy of the coordinates for every mesh point
            problem.coordsLinear = np.copy(coords.reshape(-1, 1))

            bbox = problem.dom.mesh.bounding_box_tree()

            problem.min_dist = []

            for k in range(problem.farm.numturbs):
                turbine_loc_point = Point(problem.farm.x[k], problem.farm.y[k], problem.farm.z[k])
                min_dist_node_id, dist = bbox.compute_closest_entity(turbine_loc_point)
                problem.min_dist.append(dist)

            # Create a Constant "wrapper" to enable dolfin to track mpi_u_fluid
            problem.mpi_u_fluid_constant = Constant(np.zeros((problem.farm.numturbs, 3*3*problem.num_blade_segments)),name="mpi_u_fluid")


        def init_unsteady_alm_terms(problem):

            problem.rotor_torque = np.zeros(problem.farm.numturbs)
            problem.rotor_torque_count = np.zeros(problem.farm.numturbs)
            problem.rotor_torque_dolfin = np.zeros(problem.farm.numturbs)


        def init_mpi_alm(problem):

            # Create an empty array to hold all the components of velocity
            mpi_u_fluid = np.zeros((problem.farm.numturbs, 3*3*problem.num_blade_segments))
            mpi_u_fluid_count = np.zeros((problem.farm.numturbs, 3*3*problem.num_blade_segments))

            # Calculate the angular position of the blades at the current time
            period = 60.0/problem.rpm
            # theta = (simTime+0.5*problem.dt)/period*2.0*np.pi

            # Current time at the end of the fluid solve
            simTime = problem.simTime_list[problem.simTime_id]


            # Time at the end of the previous fluid solve
            time_offset = 1

            try:
                prevTime = problem.simTime_list[problem.simTime_id - time_offset]
            except:
                prevTime = problem.simTime_list[0]

            # The velocity should be probed at the time location midway between this
            # step and the previous step
            theta = 0.5*(prevTime + simTime)/period*2.0*np.pi

            # Each turbine must be treated individually to account for varying 
            # radii, heights, positions, etc.
            for k in range(problem.farm.numturbs):

                # Get the radius of this turbine and scale the unit blade position
                R = problem.farm.radius[k]
                blade_pos = R*problem.blade_pos_base

                # Rotate the blades into the correct angular position around the x-axis
                # since the turbine blades are currently all modeled in sync, this 
                # could actually be done outside the FOR loop, but for generality and/or 
                # future out-of-phase simulations, it is left here
                blade_pos = np.dot(rot_x(theta), blade_pos)

                # Get the yaw of this turbine and rotate around the z-axis
                yaw = float(problem.farm.myaw[k])
                blade_pos = np.dot(rot_z(yaw), blade_pos)

                # Get the position of this turbine and shift the blade positions there
                x_pos = problem.farm.x[k]
                y_pos = problem.farm.y[k]
                z_pos = problem.farm.z[k]
                blade_pos[0, :] += x_pos
                blade_pos[1, :] += y_pos
                blade_pos[2, :] += z_pos

                # Need to probe the velocity point at each actuator node,
                # where actuator nodes are individual columns of blade_pos
                for j in range(np.shape(blade_pos)[1]):
                    # If using the local velocity, measure at the blade
                    if problem.farm.use_local_velocity:
                        xi = blade_pos[0, j]
                    else:
                        xi = problem.dom.x_range[0]

                    yi = blade_pos[1, j]
                    zi = blade_pos[2, j]

                    # Try to access the fluid velocity at this actuator point
                    # If this rank doesn't own that point, an error will occur,
                    # in which case zeros should be reported
                    try:
                        fn_val = problem.u_k1(np.array([xi, yi, zi]))
                        mpi_u_fluid[k, 3*j:3*j+3] = fn_val
                        mpi_u_fluid_count[k, 3*j:3*j+3] = [1, 1, 1]
                    except:
                        pass

            data_in_fluid = np.zeros((self.params.num_procs, np.shape(mpi_u_fluid)[0], np.shape(mpi_u_fluid)[1]))
            self.params.comm.Gather(mpi_u_fluid, data_in_fluid, root=0)

            data_in_count = np.zeros((self.params.num_procs, np.shape(mpi_u_fluid_count)[0], np.shape(mpi_u_fluid_count)[1]))
            self.params.comm.Gather(mpi_u_fluid_count, data_in_count, root=0)

            if self.params.rank == 0:
                mpi_u_fluid = np.sum(data_in_fluid, axis=0)
                mpi_u_fluid_count = np.sum(data_in_count, axis=0)

                # This removes the possibility of a velocity shared between multiple nodes being reported
                # multiple times and being effectively doubled (or worse) when summing mpi_u_fluid across processes
                mpi_u_fluid = mpi_u_fluid/mpi_u_fluid_count

            self.params.comm.Bcast(mpi_u_fluid, root=0)

            return mpi_u_fluid

        # ================================================================

        def finalize_mpi_alm(problem):

            data_in_torque = np.zeros((self.params.num_procs, problem.farm.numturbs))
            self.params.comm.Gather(problem.rotor_torque, data_in_torque, root=0)

            data_in_torque_count = np.zeros((self.params.num_procs, problem.farm.numturbs))
            self.params.comm.Gather(problem.rotor_torque_count, data_in_torque_count, root=0)

            if self.params.rank == 0:
                # print(data_in_torque)
                # print(data_in_torque_count)
                problem.rotor_torque = np.sum(data_in_torque, axis=0)
                problem.rotor_torque_count = np.sum(data_in_torque_count, axis=0)

                # print(problem.rotor_torque_count)

                # This removes the possibility of a power being doubled or tripled
                # if multiple ranks include this turbine and therefore calculate a torque
                problem.rotor_torque = problem.rotor_torque/problem.rotor_torque_count

            self.params.comm.Bcast(problem.rotor_torque, root=0)

        # ================================================================


        # ================================================================

        tic = time.time()
        problem.simTime_list.append(simTime)
        problem.dt_list.append(problem.dt)
        problem.rotor_torque_dolfin_time.append(0.0)

        # If this is the first call to the function, set some things up before proceeding
        if problem.simTime_id == 0:
            init_constant_alm_terms(problem)

        # Initialize summation, counting, etc., variables for alm solve
        init_unsteady_alm_terms(problem)

        # Call the function to build the complete mpi_u_fluid array
        mpi_u_fluid = init_mpi_alm(problem)

        # Populate the Constant "wrapper" with the velocity values to enable dolfin to track mpi_u_fluid
        problem.mpi_u_fluid_constant.assign(Constant(mpi_u_fluid,name="temp_u_f"))

        # Call the ALM function for each turbine individually
        alm_output_list = []
        for turb_index in range(problem.farm.numturbs):
            alm_output_list.append(UpdateActuatorLineForce(problem, problem.mpi_u_fluid_constant, problem.simTime_id, problem.dt, turb_index, dfd=dfd))
            # alm_output_list.append(UpdateActuatorLineForce_deprecated(problem, problem.u_k1, problem.simTime_id, problem.dt, turb_index, mpi_u_fluid, dfd=dfd))
            # print("tf   = "+repr(np.mean(alm_output_list[-1].vector()[:])))

        # Do some sharing of information when everything is finished
        finalize_mpi_alm(problem)

        problem.simTime_id += 1
        toc = time.time()

        if verbose:
            print("Current Optimization Time: "+repr(simTime)+ ", it took: "+repr(toc-tic)+" seconds")
            sys.stdout.flush()

        return alm_output_list



####### NOTE TO SELF turb_index is a list, got to account for that in dolfin_helper





class GridWindFarm(GenericWindFarm):
    """
    A GridWindFarm produces turbines on a grid. The params.yaml file determines
    how this grid is set up.

    Example:
        In the .yaml file you need to define::

            wind_farm: 
                #                     # Description              | Units
                HH: 90                # Hub Height               | m
                RD: 126.0             # Turbine Diameter         | m
                thickness: 10.5       # Effective Thickness      | m
                yaw: 0.0              # Yaw                      | rads
                axial: 0.33           # Axial Induction          | -
                ex_x: [-1500, 1500]   # x-extent of the farm     | m
                ex_y: [-1500, 1500]   # y-extent of the farm     | m
                grid_rows: 6          # Number of rows           | -
                grid_cols: 6          # Number of columns        | -

        This will produce a 6x6 grid of turbines equally spaced within the 
        region [-1500, 1500]x[-1500, 1500].

    Args: 
        dom (:meth:`windse.DomainManager.GenericDomain`): a windse domain object.
    """
    def __init__(self,dom):
        super(GridWindFarm, self).__init__(dom)
        Sx = self.dom.xscale

        self.fprint("Generating Grid Wind Farm",special="header")

        ### Initialize Values from Options ###
        self.numturbs = self.grid_rows * self.grid_cols
        self.params["wind_farm"]["numturbs"] = self.numturbs

        ### Scale Terms ###
        self.HH     = self.HH * Sx
        self.RD     = self.RD * Sx
        self.thickness      = self.thickness * Sx
        self.jitter = self.jitter * Sx
        self.radius = self.RD/2.0
        
        # Need to compute extents if only spacings are provided
        if self.ex_x is None:
            x_dist = self.x_spacing * (self.grid_cols - 1)
            y_dist = self.y_spacing * (self.grid_rows - 1)
            self.ex_x = [0., x_dist + 2 * self.radius]
            self.ex_y = [-y_dist / 2 - self.radius, y_dist / 2 + self.radius]
        else:
            self.ex_x   = self.ex_x * Sx
            self.ex_y   = self.ex_y * Sx

        ### Create the x and y coords ###
        if self.grid_cols > 1:
            self.grid_x = np.linspace(self.ex_x[0]+self.radius,self.ex_x[1]-self.radius,self.grid_cols)
        else:
            self.grid_x = (self.ex_x[0]+self.ex_x[1])/2.0
        if self.grid_rows > 1:
            self.grid_y = np.linspace(self.ex_y[0]+self.radius,self.ex_y[1]-self.radius,self.grid_rows)
        else:
            self.grid_y = (self.ex_y[0]+self.ex_y[1])/2.0

        ### Use the x and y coords to make a mesh grid ###
        self.x, self.y = np.meshgrid(self.grid_x,self.grid_y)
        
        # Apply y shear if included in user yaml. Shear is in meters.
        if self.y_shear is not None:
            for idx in range(self.grid_cols):
                self.y[:, idx] += self.y_shear * idx
        
        # Apply x shear if included in user yaml. Shear is in meters.
        if self.x_shear is not None:
            for idx in range(self.grid_rows):
                self.x[idx, :] += self.x_shear * idx

        self.x = self.x.flatten()
        self.y = self.y.flatten()

        ### Apply Jitter ###
        if self.jitter > 0.0:
            if self.seed is not None:
                np.random.seed(self.seed)
            self.x += np.random.randn(self.numturbs)*self.jitter
            self.y += np.random.randn(self.numturbs)*self.jitter
            
        # Recompute the extents based on grid manipulations
        self.ex_x = [np.min(self.x), np.max(self.x)]
        self.ex_y = [np.min(self.y), np.max(self.y)]
            
        ### Print some useful stats ###
        self.fprint("Force Type:         {0}".format(self.force))
        self.fprint("Number of Rows:     {:d}".format(self.grid_rows))
        self.fprint("Number of Columns:  {:d}".format(self.grid_cols))
        self.fprint("Number of Turbines: {:d}".format(self.numturbs))
        if self.jitter > 0.0:
            self.fprint("Amount of Jitter:   {: 1.2f}".format(self.jitter))
            self.fprint("Random Seed: " + repr(self.seed))
        self.fprint("X Range: [{: 1.2f}, {: 1.2f}]".format(self.ex_x[0]/Sx,self.ex_x[1]/Sx))
        self.fprint("Y Range: [{: 1.2f}, {: 1.2f}]".format(self.ex_y[0]/Sx,self.ex_y[1]/Sx))

        ### Convert the constant parameters to lists ###
        self.CreateLists()

        ### Convert the lists into lists of dolfin Constants ###
        self.CreateConstants() 

        ### Calculate Ground Heights ###
        self.CalculateHeights()

        ### Update the extent in the z direction ###
        self.ex_z = [min(self.ground),max(self.z+self.RD)]
        self.params["wind_farm"]["ex_z"] = self.ex_z

        self.DebugOutput()
        self.fprint("Wind Farm Generated",special="footer")
        

class RandomWindFarm(GenericWindFarm):
    """
    A RandomWindFarm produces turbines located randomly with a defined 
    range. The params.yaml file determines how this grid is set up.

    Example:
        In the .yaml file you need to define::

            wind_farm: 
                #                     # Description              | Units
                HH: 90                # Hub Height               | m
                RD: 126.0             # Turbine Diameter         | m
                thickness: 10.5       # Effective Thickness      | m
                yaw: 0.0              # Yaw                      | rads
                axial: 0.33           # Axial Induction          | -
                ex_x: [-1500, 1500]   # x-extent of the farm     | m
                ex_y: [-1500, 1500]   # y-extent of the farm     | m
                numturbs: 36          # Number of Turbines       | -
                seed: 15              # Random Seed for Numpy    | -

        This will produce a 36 turbines randomly located within the 
        region [-1500, 1500]x[-1500, 1500]. The seed is optional but 
        useful for reproducing test.

    Args: 
        dom (:meth:`windse.DomainManager.GenericDomain`): a windse domain object.
    """
    def __init__(self,dom):

        def generate_random_point(x_range, y_range):
            
            rand_pt = np.zeros(2)
            
            # This assigns numbers in the range (x_range[0], x_range[1])
            rand_pt[0] = np.random.uniform(x_range[0], x_range[1])
            rand_pt[1] = np.random.uniform(y_range[0], y_range[1])
            
            return rand_pt

        def build_random_samples(N, x_range, y_range, min_dist, x_padding=None, y_padding=None):
            rand_samples = np.zeros((N, 2))

            if x_padding is not None:
                x_range[0] = x_range[0] + x_padding[0]
                x_range[1] = x_range[1] - x_padding[1]

            if y_padding is not None:
                y_range[0] = y_range[0] + y_padding[0]
                y_range[1] = y_range[1] - y_padding[1]
            
            # Declare the maximum number of attempts at placing a turbine          
            maximum_iterations = 50000

            for k in range(N):
                if k == 0:
                    # The first turbine can always be added (guaranteed collision free)
                    new_pt = generate_random_point(x_range, y_range)
                    rand_samples[0, :] = new_pt

                else:
                    # Additional turbines must be tested to enforce the minimum separation distance
                    collision = True
                    attempt = 0
                    
                    while collision == True:
                        new_pt = generate_random_point(x_range, y_range)
                        attempt += 1
                                        
                        dx_2 = (rand_samples[0:k, :] - new_pt)**2
                        dist_2 = np.sum(dx_2, axis = 1)
                                        
                        if np.amin(dist_2) < min_dist**2:
                            collision = True
                        else:
                            collision = False
                            rand_samples[k, :] = new_pt

                        if attempt > maximum_iterations:
                            # If the total numer of turbines couldn't be placed, raise an error or return the incomplete list
                            # (since the list is incomplete, numturbs needs to be updated with the reduced value)
                            # raise ValueError("Couldn't place point %d of %d after %d iterations." % (k+1, N, maximum_iterations))
                            self.fprint("WARNING: Couldn't place point %d of %d after %d iterations." % (k+1, N, maximum_iterations))
                            self.fprint("WARNING: Consider reducing the number of turbines or decreasing the minimum separation distance.")
                            self.fprint("WARNING: Proceeding with incomplete random farm, numturbs = %d turbines." % (k))
                            self.numturbs = k
                            return rand_samples[0:k, :]

            return rand_samples

        super(RandomWindFarm, self).__init__(dom)
        Sx = self.dom.xscale
        self.fprint("Generating Random Farm",special="header")
        
        ### Scale Terms ###
        self.HH     = self.HH * Sx
        self.RD     = self.RD * Sx
        self.thickness      = self.thickness * Sx
        self.jitter = self.jitter * Sx
        self.radius = self.RD/2.0
        self.ex_x   = self.ex_x * Sx
        self.ex_y   = self.ex_y * Sx
        self.min_sep_dist = self.min_sep_dist * self.RD

        ### Print some useful stats ###
        self.fprint("Force Type:         {0}".format(self.force))
        self.fprint("Number of Turbines: {:d}".format(self.numturbs))
        self.fprint("X Range: [{: 1.2f}, {: 1.2f}]".format(self.ex_x[0]/Sx,self.ex_x[1]/Sx))
        self.fprint("Y Range: [{: 1.2f}, {: 1.2f}]".format(self.ex_y[0]/Sx,self.ex_y[1]/Sx))
        self.fprint("Random Seed: " + repr(self.seed))

        ### Check if random seed is set ###
        if self.seed is not None:
            np.random.seed(self.seed)

        ### Create the x and y coords ###
        # self.x = np.random.uniform(self.ex_x[0]+self.radius,self.ex_x[1]-self.radius,self.numturbs)
        # self.y = np.random.uniform(self.ex_y[0]+self.radius,self.ex_y[1]-self.radius,self.numturbs)

        rand_locations = build_random_samples(self.numturbs, self.ex_x, self.ex_y, self.min_sep_dist)

        self.x = rand_locations[:, 0]
        self.y = rand_locations[:, 1]

        ### Convert the constant parameters to lists ###
        self.CreateLists()
        
        ### Convert the lists into lists of dolfin Constants ###
        self.CreateConstants() 

        ### Calculate Ground Heights ###
        self.CalculateHeights()

        ### Update the extent in the z direction ###
        self.ex_z = [min(self.ground),max(self.z+self.RD)]
        self.params["wind_farm"]["ex_z"] = self.ex_z

        self.DebugOutput()
        self.fprint("Wind Farm Generated",special="footer")


class ImportedWindFarm(GenericWindFarm):
    """
    A ImportedWindFarm produces turbines located based on a text file.
    The params.yaml file determines how this grid is set up.

    Example:
        In the .yaml file you need to define::

            wind_farm: 
                imported: true
                path: "inputs/wind_farm.txt"

        The "wind_farm.txt" needs to be set up like this::

            #    x      y     HH           Yaw Diameter Thickness Axial_Induction
            200.00 0.0000 80.000  0.0000000000      126      10.5            0.33
            800.00 0.0000 80.000  0.0000000000      126      10.5            0.33

        The first row isn't necessary. Each row defines a different turbine.

    Args: 
        dom (:meth:`windse.DomainManager.GenericDomain`): a windse domain object.
    """
    def __init__(self,dom):
        super(ImportedWindFarm, self).__init__(dom)
        Sx = self.dom.xscale
        self.fprint("Importing Wind Farm",special="header")
        
        ### Import the data from path ###
        raw_data = np.loadtxt(self.path,comments="#")

        ### Copy Files to input folder ###
        shutil.copy(self.path,self.params.folder+"input_files/")

        ### Parse the data ###
        if len(raw_data.shape) > 1:
            self.x     = raw_data[:,0]*Sx 
            self.y     = raw_data[:,1]*Sx
            self.HH    = raw_data[:,2]*Sx
            self.yaw   = raw_data[:,3]
            self.RD    = raw_data[:,4]*Sx
            self.radius = self.RD/2.0
            self.thickness     = raw_data[:,5]*Sx
            self.axial     = raw_data[:,6]
            self.numturbs = len(self.x)

        else:
            self.x     = np.array((raw_data[0],))*Sx
            self.y     = np.array((raw_data[1],))*Sx
            self.HH    = np.array((raw_data[2],))*Sx
            self.yaw   = np.array((raw_data[3],))
            self.RD    = np.array((raw_data[4],))*Sx
            self.radius = np.array((raw_data[4]/2.0,))*Sx
            self.thickness     = np.array((raw_data[5],))*Sx
            self.axial     = np.array((raw_data[6],))
            self.numturbs = 1

        ### Update the options ###
        self.params["wind_farm"]["numturbs"] = self.numturbs
        self.fprint("Force Type:         {0}".format(self.force))
        self.fprint("Number of Turbines: {:d}".format(self.numturbs))

        ### Convert the lists into lists of dolfin Constants ###
        self.CreateConstants() 

        ### Calculate Ground Heights ###
        self.CalculateHeights()

        ### Calculate the extent of the farm ###
        self.CalculateFarmBoundingBox()
    
        self.DebugOutput()
        self.fprint("Wind Farm Imported",special="footer")


class EmptyWindFarm(GenericWindFarm):

    def __init__(self,dom):
        super(EmptyWindFarm, self).__init__(dom)
        self.numturbs  = 0
        self.x         = []
        self.y         = []
        self.z         = []
        self.HH        = []
        self.yaw       = []
        self.RD        = []
        self.radius    = []
        self.thickness = []
        self.axial     = []
        self.ex_x      = [0,0]
        self.ex_y      = [0,0]
        self.ex_z      = [0,0]
