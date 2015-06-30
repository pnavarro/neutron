# Copyright (c) 2013 OpenStack Foundation.
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

import neutron.db.api as db_api
from sqlalchemy.orm import exc

from sqlalchemy import sql

from neutron.db import models_v2
from neutron.plugins.ml2 import models as ml2_models


class TelefonicaDbMixin(object):

    def get_network_portbindings(self, network_id):
        session = db_api.get_session()
        try:
            query = session.query(ml2_models.PortBinding)
            query = query.join(models_v2.Port)
            query = query.filter(models_v2.Port.network_id == network_id,
                                 models_v2.Port.admin_state_up == sql.true())
        except exc.NoResultFound:
            query = None
        return query

    def get_network_ports(self, network_id):
        session = db_api.get_session()
        try:
            query = session.query(models_v2.Port)
            query = query.filter(models_v2.Port.network_id == network_id,
                                 models_v2.Port.admin_state_up == sql.true(),
                                 models_v2.Port.device_owner.isnot(None))
        except exc.NoResultFound:
            query = None
        return query.all()

    def get_port_by_id(self, port_id):
        session = db_api.get_session()
        try:
            query = session.query(models_v2.Port)
            query = query.filter(models_v2.Port.id.startswith(port_id))
            port = query.one()
            if not port:
                return
        except exc.NoResultFound:
            port = None
        return port