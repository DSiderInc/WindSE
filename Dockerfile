FROM python:3.9

ENV PATH="/root/miniconda3/bin:${PATH}"
ARG PATH="/root/miniconda3/bin:${PATH}"
RUN apt-get update

RUN apt-get install -y wget && rm -rf /var/lib/apt/lists/*

RUN mkdir /root/miniconda3 
RUN wget \
    https://repo.anaconda.com/miniconda/Miniconda3-py39_22.11.1-1-Linux-x86_64.sh 
RUN sh Miniconda3-py39_22.11.1-1-Linux-x86_64.sh -b
RUN rm -f Miniconda3-py39_22.11.1-1-Linux-x86_64.sh
RUN conda --version

COPY . /WindSE
WORKDIR /WindSE

RUN sh install.sh windse

# RUN python3 -m pip install --upgrade pip
# # libs for git?
# RUN apt update && apt install -y \
#     libz-dev \
#     libssl-dev \
#     libcurl4-gnutls-dev \
#     libexpat1-dev \
#     gettext \
#     cmake \
#     gcc

# RUN apt-get update && apt-get install -y \
#     build-essential \
#     libboost-dev \
#     libopenblas-dev \
#     libhdf5-dev \
#     git \
#     fenics

# # changed hdf5 to h5py
# RUN conda install -c conda-forge dolfin-adjoint fenics matplotlib scipy slepc pyyaml memory_profiler pytest pytest-cov pytest-mpi coveralls h5py

# RUN pip3 install git+https://github.com/dolfin-adjoint/pyadjoint.git@2019.1.0

# RUN pip3 install git+https://github.com/blechta/tsfc.git@2018.1.0
# RUN pip3 install git+https://github.com/blechta/FInAT.git@2018.1.0
# RUN pip3 install git+https://github.com/mdolab/pyoptsparse@v1.0
# RUN pip3 install git+https://github.com/blechta/COFFEE.git@2018.1.0
# RUN pip3 install singledispatch networkx pulp openmdao

# # build mshr ?? mshr

# RUN pip3 install -e .