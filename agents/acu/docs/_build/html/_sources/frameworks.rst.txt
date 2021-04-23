Frameworks Overview
===================

Our two target frameworks are:

- Requests: By which we mean the classic ``requests`` library in
  Python, which runs well in the usual synchronous Python interpreter.
- Twisted: The asynchronous framework in which OCS operates.

The reason we want to support Twisted is that it is the core framework
for OCS Agents and is well-suited to the problem at hand (serving
requests externally while managing the ACU through an http interface).

The reason that we want to support Requests is that debugging Twisted
code can be awkward, and ``requests``-based code will run with many
fewer dependencies.

The aculib exposes a primary user interface through the AcuControl
class.  The propagation of commands and queries from the user to ACU
are layered as follows:

- ACUControl - the top-level class through which a user makes all
  commands/queries.

  - The API methods in ACUControl issue commands/queries to the ACU
    through the basic interfaces defined in AcuHttpInterface, or
    through calls to other API methods.
  - AcuHttpInterface describes the protocol understood by the ACU;
    namely it abstracts the creation of HTTP requests for the ACU
    "Values", "Command" and "Write" plugins.  The AcuHttpInterface
    does not issue HTTP requests, but instead constructs HttpRequest
    objects.

    - HttpRequest objects contain an abstracted description of an HTTP
      request that can be passed to a Backend.  In addition to the
      usual HTTP request parameters (such URL, parameters, and POST
      data), the HttpRequest also has an associated decoder for the
      output.  This permits output to be reformatted in a standard way
      (e.g. some function return JSON, and this could be automatically
      decoded into Python data structures; in other cases the decoder
      might inspect the HTTP return code to assess success of the
      operation).

  - The Backend object (StandardBackend or TwistedBackend) is
    responsible for executing the request stored in the HttpRequest
    object.  Using appropriate methods for the target framework, it
    issues the HTTP request and runs the output through the decoder.

    - The StandardBackend returns the decoded data from the request,
      or the structured error information.
    - The TwistedBackend returns a Deferred for each HttpRequest,
      whose ultimate result is the decoded data or structured error
      information (i.e. upon resolution of the Deferred you get the
      same thing the StandardBackend would return.


The abstraction in the Backend is an important component, but it is
not enough for full abstraction.  The high level methods in AcuControl
that use the abstracted Backend to execute an HttpRequest must know
what to do with the object that comes back to them.  In Requests, the
result could be used directly::

    def check_values(req1, req2):
        if self.backend(req1)[0] == 'OK':
            if self.backend(req2)[0] == 'OK':
                return "Both are OK."
        return "One or the other are not OK."

But in Twisted, you have to work in the language of generators::

    @inlineCallbacks
    def check_values(req1, req2):
        result1 = yield self.backend(req1)
        if result1[0] == 'OK':
            result2 = yield self.backend(req2)
            if result2[0] == 'OK':
                returnValue("Both are OK.")
        returnValue("One or the other are not OK.")

Here's another psuedo-ish code example::

    def wait_arrived_requests(az):
        while True:
            position = self.get_az_pos()
            if (abs(position-az) < .001):
                returnValue('OK')
            sleep(1)

    @inlineCallbacks
    def wait_arrived_twisted(az):
        while True:
            position = yield self.get_az_pos()
            if (abs(position-az) < .001):
                return 'OK'
            yield dsleep(1)


The code in these two cases is very similar, so it is really a shame
that we need to implement it twice.  The benefits of the abstraction
are mostly lost, since it is the more complex functions (that make
multiple calls) that are more likely to require alteration.

The solution we are pursuing in aculib is to write all the code using
generators, but to wrap that code differently depending on the
framework.  For twisted, we wrap it using inlineCallbacks.  For
Requests, we wrap it using a simple function that essentially drives
the generator in a similar way to how inlineCallbacks does.

This has an impact on how code must be written in the AcuControl
class.  Here are the rules:

- Implementation of the API functions should have names with a leading
  underscore, e.g. ``_stop()``.  In the class constructor, these will
  be wrapped in a backend-dependent way, producing the public API
  (i.e. ``stop()``).
- Internally, calls to other API functions must use the internal
  names.  I.e. the ``_stop()`` function implementation might want to
  set the mode, for which it should use the ``_mode()`` function, not
  the ``mode()`` function.
- Internally, calls to other API functions and to the http request
  generator must use Twisted-style ``yield`` semantics to get the
  return value from them.  To get the current mode, you would use
  ``result = yield self._mode()``, for example.  The function
  decorators provided by the backend will cause this to do a sensible
  thing -- get a *value* from ``self._mode()`` and put it into the
  variable called ``result``.
- To return a value from an API function, you must use
  ``self._return(value)``.  This works by raising an Exception, that
  is caught by the function decorator.  So the function where this
  appears will always stop executing at that point.  Note that
  ``return value`` will probably cause a value of None to be returned,
  regardless of what is in value.
