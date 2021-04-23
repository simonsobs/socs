==============
ACU Interfaces
==============

References
==========

ACU ICD 2.0

The http interface(s)
=====================

The ACU has a few different basic kinds of HTTP interface, called
*Plugins*.  The main command and monitoring interfaces use the
following Plugins:

- Values
- Command
- Write
- UploadPtStack
- GetPtStack

Other Plugins, more useful during development / debugging:

- Documentation - Returns various descriptions of a module; see ICD.
- Meta (no parameters) - returns data structure information that can
  be used to parse results from the Values plugin; see ICD.
- Version (no parameters) - returns version codes for various ACU
  internals.
- List (no parameters) - returns a list of valid module identifiers.

The interfaces make use of either the GET or POST type of HTTP
requests.  Both of these have "Parameters", passed through the URL.
Additionally POST has "Data", passed through the message body.


Value Plugin
------------

Parameters:

- Identifier (e.g. ``Antenna.SkyAxes.Elevation``)
- Type - optional (default is `Actual`) - one of:

  - `Actual` - Returns the actual (current) values.
  - `Target` - Returns the target values.
  - `Parameter` - Returns the parameters.

- Format - optional (default is a system config param?) - one of:

  - `ASCII`
  - `Binary`
  - `HTML`
  - `JSON`
  - `SSV`
  - `XML`

HTTP encoding is via GET::

  /Values?identifier={Identifier}&type={Type}&format={Format}

Returns:

- HTTP 200 (ok) and the data in the requested format.
- HTTP 204 (No Content) and no content in the case of invalid
  Identifier or Type.
- HTTP 400 (Bad Request) and no data in the case of invalid Format.


Command Plugin
--------------

Parameters:

- Identifier (e.g. ``DataSets.CmdAzElPositionTransfer``)
- Command (e.g. ``Set Azimuth``)
- Parameter (e.g. ``61.00``).  Note that multiple parameters are
  joined with a pipe, ``|``, e.g. ``61.00|76.50``.

HTTP encoding is via GET::

  /Command?identifier={Identifier}&command={Command}&parameter={Parameter}

Returns:

- In successful cases returns HTTP code 200 (OK) and text: ``OK,
  Command executed.``
- In some error cases returns HTTP code 200 (OK) and error text:
  ``Failed: Invalid/Unknown value!``
  - This has been seen to occur in cases where the Identifier or
    Parameter are invalid.
- In some error cases returns HTTP code 200 (OK) and error text:
  ``Failed: Unknown command!``
  - This has been seen to occur in cases where the Command is invalid.


Write Plugin
--------------

Parameters:

- Identifier (e.g. ``DataSets.CmdAzElPositionTransfer``)

HTTP encoding is via POST::

  /Write?identifier={Identifier}

The POST Data payload is binary-encoded data specific to the DataSet.
For example, for DataSets.CmdAzElPositionTransfer, the structure
consists of two double-precision floats, for AZ and EL in that order.

Returns: ?

