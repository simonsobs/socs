.. highlight:: bash

.. _sequencer:

=========
Sequencer
=========

Overview
========

The 'Sequencer' is a tool with a graphical front end that can be used to run
OCS Clients. Often this will be done with the help of another library,
enabling the command of many Clients in sequence. This page describes the
configuration and use of the Sequencer.

Description
===========

The Sequencer tool is called `nextline
<https://github.com/simonsobs/nextline>`_. Nextline is composed of a `backend
<https://github.com/simonsobs/nextline-graphql>`_ API, which uses GraphQL, and a
graphical `frontend <https://github.com/simonsobs/nextline-web>`_ written in
VueJS. The graphical front end is accessible in your web browser and provides
an interface for running Python code. The code is passed to and executed on the
backend.

Typically these components will run in two separate Docker containers. In
practice you will have these both behind a reverse proxy. This proxy server may
be in another container. For the purposes of this page we will use an nginx
proxy in a separate container (similar to the one described in
:ref:`webserver`.)

In order to orchestrate many OCS Clients, we use a helper library called
`sorunlib <https://github.com/simonsobs/sorunlib>`_. For setup of nextline with
sorunlib we provide a pre-build Docker image called the `so-daq-sequencer
<https://github.com/simonsobs/so-daq-sequencer-docker/pkgs/container/so-daq-sequencer>`_.

Setup
=====
Here we setup an example set of Docker containers which make nextline available
on your localhost. Here is an example ``docker-compose.yml`` file that provides
both nextline components, an nginx reverse proxy, and persistent storage for
the backend database:

.. code-block:: yaml

  version: '3.7'

  networks:
    default:
      external:
        name: ocs-net

  services:
    frontend:
      image: ghcr.io/simonsobs/nextline-web:latest
      container_name: nextline-web
      environment:
        - API_HTTP=http://localhost/nextline/api/
        - PUBLIC_PATH=/nextline/

    backend:
      image: ghcr.io/simonsobs/so-daq-sequencer:latest
      container_name: nextline-backend
      environment:
        - NEXTLINE_DB__URL=sqlite:////db/db.sqlite3
        - OCS_CONFIG_DIR=/config
      volumes:
        - /srv/sequencer/db:/db
        - ${OCS_CONFIG_DIR}:/config:ro

    nginx:
      image: nginx:latest
      restart: always
      volumes:
       - ./nginx.conf:/etc/nginx/nginx.conf:ro
      ports:
       - "127.0.0.1:80:80"

.. note::
    This example makes use of the externally defined network "ocs-net". This is
    to allow the backend to connect to the crossbar server. Your needs may differ
    depending on your network configuration. For details on an "ocs-net" like
    configuration see the `OCS Docs
    <https://ocs.readthedocs.io/en/main/user/docker_config.html#considerations-for-deployment>`_.

.. note::
    Your site-config-file must point to the crossbar address as if from the
    container running the so-daq-sequencer by default, otherwise the sequencer
    will be unable to connect. We are working on solution/recommended
    configuration upstream in OCS. Until that is solved be aware that this
    may limit local commanding via other methods like running control programs
    on the commandline.

:ref:`webserver` has a full example of ``nginx.conf``. What we need to add to
that config is:

.. code-block:: nginx

    http {
      # Nextline Websocket Connection
      # For websocket connection upgrade
      # https://www.nginx.com/blog/websocket-nginx/
      map $http_upgrade $connection_upgrade {
        default upgrade;
        ''      close;
      }

      server {
          ...

        location /nextline/ {
          proxy_pass http://nextline-web/nextline/;

          #auth_basic "Restricted Content";
          #auth_basic_user_file /etc/nginx/.htpasswd;
        }

        location /nextline/api/ {
          proxy_pass http://nextline-backend:8000/;

          # https://www.nginx.com/blog/websocket-nginx/
          proxy_http_version 1.1;
          proxy_set_header Upgrade $http_upgrade;
          proxy_set_header Connection $connection_upgrade;
          proxy_set_header Host $host;

          #auth_basic "Restricted Content";
          #auth_basic_user_file /etc/nginx/.htpasswd;
        }
      }
    }

.. warning::
    You absolutely must put the Sequencer behind some form on authentication.
    The entire point of the tool is remote code execution, making it dangerous
    if exposed to the open internet.

Once you bring these containers up (with ``docker compose up -d``), you should
be able to access the Sequencer by pointing your web browser to
http://localhost/nextline/.

.. note::
    This configuration will get you a standalone local nextline behind a proxy.
    To run nextline on a public facing URL you need to set ``API_HTTP``
    appropriately. For example:

    .. code-block:: yaml

      - API_HTTP=https://example.com/nextline/api/
