#!/usr/bin/env python

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


"""
Glare (Glance Artifact Repository) API service
"""

import sys

import eventlet
from oslo_utils import encodeutils

eventlet.patcher.monkey_patch(all=False, socket=True, time=True,
                              select=True, thread=True, os=True)

import glance_store
from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging
import osprofiler.notifier
import osprofiler.web

from glare.common import config
from glare.common import exception
from glare.common import wsgi
from glare import notification


CONF = cfg.CONF
CONF.import_group("profiler", "glare.common.wsgi")
logging.register_options(CONF)

KNOWN_EXCEPTIONS = (RuntimeError,
                    exception.WorkerCreationFailure,
                    glance_store.exceptions.BadStoreConfiguration)


def fail(e):
    global KNOWN_EXCEPTIONS
    return_code = KNOWN_EXCEPTIONS.index(type(e)) + 1
    sys.stderr.write("ERROR: %s\n" % encodeutils.exception_to_unicode(e))
    sys.exit(return_code)


def main():
    try:
        config.parse_args()
        wsgi.set_eventlet_hub()
        logging.setup(CONF, 'glare')

        if cfg.CONF.profiler.enabled:
            _notifier = osprofiler.notifier.create(
                "Messaging", oslo_messaging, {}, notification.get_transport(),
                "glare", "artifacts", cfg.CONF.bind_host)
            osprofiler.notifier.set(_notifier)
        else:
            osprofiler.web.disable()

        server = wsgi.Server(initialize_glance_store=True)
        server.start(config.load_paste_app('glare-api'), default_port=9494)
        server.wait()
    except KNOWN_EXCEPTIONS as e:
        fail(e)


if __name__ == '__main__':
    main()
