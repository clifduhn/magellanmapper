# Installation of MagellanMapper

MagellanMapper can be installed many different ways dependening on one's Python preferences.

## Recommended: Install in a Conda environment

Conda greatly simplifies installation by managing all supporting packages, such as Java and packages that would otherwise need to be compiled. Conda's virtual environment also keeps these packages separate from other Python package installations that may be on your system.

After downloading MagellanMapper, create a new Conda environment with all dependent packages installed using this command:

```
conda env create -n mag magellanmapper/environment.yml
```

**Convenient alternative**: On Mac, Linux, or a Bash shell in Windows, this setup script perform this full installation including installing Conda if not already present:

```
magellanmapper.bin/setup_conda.sh [-n name] [-s spec]
```

This script will install:

- If not already present: [Miniconda](https://conda.io/miniconda.html), a light version of the Anaconda package and environment manager for Python
- A Conda environment with Python 3, named according to the `-n` option, or `mag` by default
- Full dependencies based on `environment.yml`, or an alternative specification if the `-s` option is given, such as `-s environment_light.yml` for headless systems that do not require a GUI

## Option 2: Install through Venv+Pip

Venv is a virtual environment manager included with Python 3.3+. We have provided a convenient script to set up a new environment and install all dependencies using Pip:

```
magellanmapper/bin/setup_venv.sh [-n name]
```

This option assumes that you have already installed Python 3.6 and a Java Development Kit (JDK) 8. Other versions of Python 3 and the JDK may work but with varying other requirements, such as a C compiler to build dependencies (see [below](#custom-precompiled-packages)).

This setup script will check and install the following dependencies:

- Checks for an existing Python 3.6+, which already includes Venv
- Performs a Pip install of MagellanMapper and all dependencies

## Option 3: Install in another virtual environment or system-wide

Whether in a virtual environment of your choice or none at all, MagellanMapper can be installed through Pip:

```
pip install -e magellanmapper --extra-index-url https://pypi.fury.io/dd8/
```

The extra URL provides pre-built custom (with [certain requirements](#custom-precompiled-packages)) dependency packages. To include all dependencies, run this command instead:

```
pip install -e magellanmapper[all] --extra-index-url https://pypi.fury.io/dd8/
```

### Option 4: Even more installation methods

You can also install MagellanMapper these ways in the shell and Python environment of your choice:

- In a Python environment of your choice or none at all, run `pip install -r requirements.txt` to match dependencies in a pinned, current test setup (cross-platform)
- To create a similar environment in Conda, run `conda env create -n [name] -f environment_[os].yml`, where `name` is your desired environment name, and `os` is `win|mac|lin` for your OS (assumes 64-bit)
- To install without Pip, run `python setup.py install` to install the package and only required dependencies

## Dependencies

The main required and optional dependencies in MagellanMapper are:

- Scipy, Numpy, Matplotlib stack
- Mayavi/TraitsUI/Qt stack for GUI and 3D visualization
- Scikit-image for image processing
- Scikit-learn for machine learning based stats
- Pandas for stats
- [SimpleElastix](https://github.com/SuperElastix/SimpleElastix), a fork of SimpleITK with Elastix integrated (see below)
- Python-Bioformats/Javabridge for importing images from propriety formast such as `.czi` (optional, requires Java SDK and C compiler)

### Optional Dependency Build and Runtime Requirements

In most cases MagellanMapper can be installed without a compiler by using custom dependency packages we have provided (see Conda pathway above). Where possible, we have made these dependencies optional for those who would prefer not to use the custom packages. They may also be compiled directly as described here.

### Custom precompiled packages

| Dependency | Precompiled Available? | Build Req | Precompiled Run Req | Purpose | 
| --- | --- | --- | --- | --- |
| Python-Javabridge | Yes, via custom package | JDK, C compiler| Python 3.6, Java 8 | Import proprietary image formats |
| Traits | Yes, via Conda (not PyPI) | n/a | C compiler | GUI |
| SimpleElastix | Yes, via custom package | Python 3.6 | C, C++ compilers | Load medical 3D formats, image regsitration |
| ImageJ/FIJI | Yes, via direct download | n/a | Java 8 | Image stitching |

C compilers by platform:

- Mac and Linux: `gcc`/`clang`
- Windows: Microsoft Visual Studio Build Tools (tested on 2017, 2019) along with these additional components
  - MSVC C++ x64/x86 build tools
  - Windows 10 SDK

Java versions:

- The Conda setup pathway installs JDK 8
- Python-Javabridge uses JDK v8-13 (v12+ in latest Git commits)
- ImageJ/Fiji supports Java 8

Our custom packages assume an environment with Python 3.6 and Java 8.

### Additional optional packages

- R for additional stats
- Zstd (fallback to Zip) for compression on servers
- MeshLab for 3D surface clean-up

### SimpleElastix dependency

SimpleElastix is used for loading many 3D image formats (eg `.mhd/.raw` and `.nii`) and registration tasks in MagellanMapper. The library is not currently available in the standard [PyPi](https://pypi.org/). As the buid process is not trivial, we have uploaded binaries to a [third-party PyPi server](https://pypi.fury.io/dd8/).

If you would prefer to build SimpleElastix yourself, we have provided a couple build scripts to ease the build process for the SimpleElastix Python wrapper:

- Mac or Linux: Run the environment setup with `bin/setup_conda.sh -s` to build and install SimpleElastix during setup using the `bin/build_se.sh` script. SimpleElastix can also be built after envrionment setup by running this script within the environment. Building SimpleElastix requires `cmake`, `gcc`, `g++`, and related compiler packages.
- Windows: Run `bin\build_se.bat` within your environment. See above for required Windows compiler components. Note that CMake 3.14 in the MSVC 2019 build tools package has not worked for us, but CMake 3.15 from the official download site has worked.

As an alternative, the SimpleITK package can provide much of the same functionality except for our image registration pipeline.

## Tested Platforms

MagellanMapper has been built and tested to build on:

- MacOS, tested on 10.11-10.15
- Linux, tested on RHEL 7.4-7.5, Ubuntu 18.04-19.10
- Windows, tested on Windows 10 (see below for details) in various environments:
  - Native command-prompt and PowerShell
  - Via built-in Windows Subsystem for Linux (WSL), tested on Ubuntu 18.04 and an X Server
  - Bash scripts in Cygwin (tested on Cygwin 2.10+) and MSYS2