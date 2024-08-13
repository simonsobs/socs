.. highlight:: bash

.. _webserver:

================
Web Server Setup
================

A web server is useful for some components of OCS and the associated live
monitoring. You might already have one setup, and are certainly welcome to run
one however you'd like. If you do not have one setup, this page describes how
to get a simple nginx server running in a docker container.

nginx
=====
nginx is a lightweight, open source, web server which we will use as a reverse
proxy.

Docker Compose Configuration
----------------------------
We will setup nginx in a docker container. First, ensure you do not currently
have a web server running (we need to make sure port 80 is available.) Then add
nginx to your docker compose file::

  web:
    image: nginx
    volumes:
     - ./nginx.conf:/etc/nginx/nginx.conf:ro
     - ./.htpasswd:/etc/nginx/.htpasswd:ro
    ports:
     - "80:80"

There are two files mounted within the container in this block, ``nginx.conf``
and ``.htpasswd``. These store the nginx configuration and authentication
credentials, respectively.

A template for ``nginx.conf`` can be found in the
``ocs-site-configs/templates`` directory, and is based on the default nginx
configuration file provided within the nginx docker image.

::

    user       nginx;  ## Default: nobody
    worker_processes  1;  ## Default: 1

    error_log  /var/log/nginx/error.log;
    pid        /var/run/nginx.pid;
    worker_rlimit_nofile 8192;

    events {
      worker_connections  1024;  ## Default: 1024
    }

    http {
      include    /etc/nginx/mime.types;
      #include    /etc/nginx/proxy.conf;
      #include    /etc/nginx/fastcgi.conf;
      index    index.html index.htm index.php;

      default_type application/octet-stream;
      log_format   main '$remote_addr - $remote_user [$time_local]  $status '
        '"$request" $body_bytes_sent "$http_referer" '
        '"$http_user_agent" "$http_x_forwarded_for"';
      access_log   /var/log/nginx/access.log  main;
      sendfile     on;
      tcp_nopush   on;
      server_names_hash_bucket_size 128; # this seems to be required for some vhosts

      server { # simple reverse-proxy
        listen       80;
        server_name  {{ domain }};
        access_log   /var/log/nginx/{{ domain }}.log  main;
        root         /usr/share/nginx/html;

        # serve static files
        # location ~ ^/(images|javascript|js|css|flash|media|static)/  {
        #   root    /var/www/virtual/big.server.com/htdocs;
        #   expires 30d;
        # }

        auth_basic "Restricted Content";
        auth_basic_user_file /etc/nginx/.htpasswd;

        location /grafana/ {
          proxy_pass http://grafana:3000/;
        }
      }
    }

.. note::
    This assumes the "web" container is running on the same network as a
    container called "grafana" for name resolution. If your setup is different you
    will need to change the URL in the ``proxy_pass`` accordingly.

``.htpasswd`` can be generated using htpasswd_. It can also be generated at
htaccesstools.com_. It will look something like this::

    user:$apr1$dJ70NC/m$r4CIcSEDK4L38HD4QH5Ix/

.. warning::
    Do NOT use the above as your ``.htpasswd`` file, it is not secure.

.. _htpasswd: https://httpd.apache.org/docs/current/programs/htpasswd.html
.. _htaccesstools.com: https://www.htaccesstools.com/htpasswd-generator/

Once you have created these two files you can bring up the webserver with::

    $ sudo docker compose up -d

Your webserver should now be accessible via the configured domain, or through
`http://localhost <http://localhost>`_.

Grafana Proxy
-------------
If you are proxying Grafana and accessing it externally (i.e. not on
``localhost``), then you need to configure several additional environment
variables. In your docker compose configuration file add::

    environment:
      - GF_SERVER_ROOT_URL=http://{{ domain }}/grafana
      - GF_SERVER_PROTOCOL=http
      - GF_AUTH_BASIC_ENABLED=false

HTTPS Setup
===========
A secure HTTPS setup might be beyond the scope of this documentation. It is,
however, possible to setup Nginx with an Let's Encrypt certificate within a set
of docker containers. `This blog post
<https://medium.com/@pentacent/nginx-and-lets-encrypt-with-docker-in-less-than-5-minutes-b4b8a60d3a71>`_
does a great job of explaining the setup.
