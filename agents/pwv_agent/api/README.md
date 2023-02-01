PWV API
=======

A small Flask app for serving the latest PWV values from text file.

This app is built to server the files from the UCSC server, and relies on the
current output format and naming conventions in place. If those get change this
will need updating.

Dependencies
------------
There are a couple of python modules we need:
* flask
* gunicorn

Running the App
---------------
The app needs to know where to get the data. You can config this by setting the
``PWV_DATA_DIR`` environment variable. We then run the app with gunicorn.

```bash
$ export PWV_DATA_DIR=/path/to/data/
$ gunicorn -c gunicorn.conf.py pwv_web:app
```

You can then navigate to http://127.0.0.1:5000 to view the latest PWV value and
timestamp.
