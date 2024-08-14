from setuptools import find_packages, setup

import versioneer

with open("README.rst", "r", encoding="utf-8") as fh:
    long_description = fh.read()

# Optional Dependencies
# ACU Agent
acu_deps = [
    # 'soaculib @ git+https://github.com/simonsobs/soaculib.git@master',
    'pixell',
    'so3g',
]

# Holography FPGA and Synthesizer Agents
# holography_deps = [  # Note: supports python 3.8 only!
#     'casperfpga @ git+https://github.com/casper-astro/casperfpga.git@py38',
#     'holog_daq @ git+https://github.com/McMahonCosmologyGroup/holog_daq.git@main',
# ]

# Labjack Agent
labjack_deps = [
    'labjack-ljm',
    'numexpr',
    'scipy',
]

# Magpie Agent
magpie_deps = [
    'pandas',
    'scipy',
    'so3g',
]

# Pfeiffer TC 400 Agent
pfeiffer_deps = ['pfeiffer-vacuum-protocol==0.4']

# Pysmurf Controller Agent
pysmurf_deps = [
    'pyepics',
    # 'pysmurf @ git+https://github.com/slaclab/pysmurf.git@main',
    # 'sodetlib @ git+https://github.com/simonsobs/sodetlib.git@master',
    # 'sotodlib @ git+https://github.com/simonsobs/sotodlib.git@master',
]

# SMuRF File Emulator, SMuRF Stream Simulator
smurf_sim_deps = ['so3g']

# Timing Master Monitor
timing_master_deps = ['pyepics']

# LATRt XY Stage Agent
# xy_stage_deps = [
#     'xy_stage_control @ git+https://github.com/kmharrington/xy_stage_control.git@main',
# ]

# Note: Not including the holograph deps, which are Python 3.8 only. Also not
# including any dependencies with only direct references.
all_deps = acu_deps + labjack_deps + magpie_deps + pfeiffer_deps + \
    pysmurf_deps + smurf_sim_deps + timing_master_deps
all_deps = list(set(all_deps))

setup(
    name='socs',
    long_description=long_description,
    long_description_content_type="text/x-rst",
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
    description='Simons Observatory Control System',
    package_dir={'socs': 'socs'},
    packages=find_packages(),
    package_data={'socs': [
        'agents/smurf_file_emulator/*.yaml',
        'agents/labjack/cal_curves/*.txt',
        'agents/generator/*.yaml'
    ]},
    entry_points={
        'console_scripts': [
            'suprsync=socs.db.suprsync_cli:main'
        ],
        'ocs.plugins': [
            'socs = socs.plugin',
        ],
    },
    url="https://github.com/simonsobs/socs",
    project_urls={
        "Source Code": "https://github.com/simonsobs/ocs",
        "Documentation": "https://ocs.readthedocs.io/",
        "Bug Tracker": "https://github.com/simonsobs/ocs/issues",
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: BSD License",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Astronomy",
        "Framework :: Twisted",
    ],
    python_requires=">=3.7",
    install_requires=[
        'autobahn[serialization]',
        'numpy',
        'ocs',
        'pyModbusTCP',
        'pyserial',
        'pysnmp==4.4.12',
        'pysmi',
        'pyyaml',
        'requests',
        'sqlalchemy>=1.4',
        'twisted',
        'pyasn1==0.4.8',
    ],
    extras_require={
        'all': all_deps,
        'acu': acu_deps,
        # 'holography': holography_deps,
        'labjack': labjack_deps,
        'magpie': magpie_deps,
        'pfeiffer': pfeiffer_deps,
        'pysmurf': pysmurf_deps,
        'smurf_sim': smurf_sim_deps,
        'timing_master': timing_master_deps,
        # 'xy_stage': xy_stage_deps,
    },
)
