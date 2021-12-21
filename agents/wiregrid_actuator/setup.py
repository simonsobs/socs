#Setup script for gclib python wrapper
# run 'python setup.py install' at console
from distutils.core import setup
setup(name='gclib', 
version='1.0',
description='Python wrapper for Galil gclib',
author='Galil Motion Control',
author_email='softwaresupport@galil.com',
url='http://www.galil.com',
py_modules=['gclib'],
)
