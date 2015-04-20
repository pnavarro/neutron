# Copyright (c) 2013 OpenStack Foundation
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

"""Exceptions used by Telefonica ML2 mechanism driver."""

from neutron.common import exceptions

class TelefonicaPortBindingNotFound(exceptions.NeutronException):
    """NexusPort Binding is not present."""
    message = _("Telefonica Port Binding (%(filters)s) is not present")

    def __init__(self, **kwargs):
        filters = ','.join('%s=%s' % i for i in kwargs.items())
        super(TelefonicaPortBindingNotFound, self).__init__(filters=filters)