"""
Support for the IKEA Tradfri platform.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/light.tradfri/
"""
import asyncio
import logging

from homeassistant.core import callback
import homeassistant.util.color as color_util
from homeassistant.components.light import (
    ATTR_BRIGHTNESS, ATTR_COLOR_TEMP, ATTR_XY_COLOR, ATTR_TRANSITION,
    SUPPORT_BRIGHTNESS, SUPPORT_TRANSITION, SUPPORT_COLOR_TEMP,
    SUPPORT_XY_COLOR, ATTR_RGB_COLOR, Light)
from homeassistant.components.light import \
    PLATFORM_SCHEMA as LIGHT_PLATFORM_SCHEMA
from homeassistant.components.tradfri import KEY_GATEWAY, KEY_TRADFRI_GROUPS, \
    KEY_API

_LOGGER = logging.getLogger(__name__)

ATTR_TRANSITION_TIME = 'transition_time'
DEPENDENCIES = ['tradfri']
PLATFORM_SCHEMA = LIGHT_PLATFORM_SCHEMA
IKEA = 'IKEA of Sweden'
TRADFRI_LIGHT_MANAGER = 'Tradfri Light Manager'
SUPPORTED_FEATURES = (SUPPORT_BRIGHTNESS | SUPPORT_TRANSITION)


@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Set up the IKEA Tradfri Light platform."""
    if discovery_info is None:
        return

    gateway_id = discovery_info['gateway']
    api = hass.data[KEY_API][gateway_id]
    gateway = hass.data[KEY_GATEWAY][gateway_id]

    devices_command = gateway.get_devices()
    devices_commands = yield from api(devices_command)
    devices = yield from api(devices_commands)
    lights = [dev for dev in devices if dev.has_light_control]
    if lights:
        async_add_devices(TradfriLight(light, api) for light in lights)

    allow_tradfri_groups = hass.data[KEY_TRADFRI_GROUPS][gateway_id]
    if allow_tradfri_groups:
        groups_command = gateway.get_groups()
        groups_commands = yield from api(groups_command)
        groups = yield from api(groups_commands)
        if groups:
            async_add_devices(TradfriGroup(group, api) for group in groups)


class TradfriGroup(Light):
    """The platform class required by hass."""

    def __init__(self, light, api):
        """Initialize a Group."""
        self._api = api
        self._group = light
        self._name = light.name

        self._refresh(light)

    @asyncio.coroutine
    def async_added_to_hass(self):
        """Start thread when added to hass."""
        self._async_start_observe()

    @property
    def should_poll(self):
        """No polling needed for tradfri group."""
        return False

    @property
    def supported_features(self):
        """Flag supported features."""
        return SUPPORTED_FEATURES

    @property
    def name(self):
        """Return the display name of this group."""
        return self._name

    @property
    def is_on(self):
        """Return true if group lights are on."""
        return self._group.state

    @property
    def brightness(self):
        """Return the brightness of the group lights."""
        return self._group.dimmer

    @asyncio.coroutine
    def async_turn_off(self, **kwargs):
        """Instruct the group lights to turn off."""
        yield from self._api(self._group.set_state(0))

    @asyncio.coroutine
    def async_turn_on(self, **kwargs):
        """Instruct the group lights to turn on, or dim."""
        keys = {}
        if ATTR_TRANSITION in kwargs:
            keys['transition_time'] = int(kwargs[ATTR_TRANSITION]) * 10

        if ATTR_BRIGHTNESS in kwargs:
            if kwargs[ATTR_BRIGHTNESS] == 255:
                kwargs[ATTR_BRIGHTNESS] = 254

            yield from self._api(
                self._group.set_dimmer(kwargs[ATTR_BRIGHTNESS], **keys))
        else:
            yield from self._api(self._group.set_state(1))

    @callback
    def _async_start_observe(self, exc=None):
        """Start observation of light."""
        # pylint: disable=import-error
        from pytradfri.error import PytradfriError
        if exc:
            _LOGGER.warning("Observation failed for %s", self._name,
                            exc_info=exc)

        try:
            cmd = self._group.observe(callback=self._observe_update,
                                      err_callback=self._async_start_observe,
                                      duration=0)
            self.hass.async_add_job(self._api(cmd))
        except PytradfriError as err:
            _LOGGER.warning("Observation failed, trying again", exc_info=err)
            self._async_start_observe()

    def _refresh(self, group):
        """Refresh the light data."""
        self._group = group
        self._name = group.name

    @callback
    def _observe_update(self, tradfri_device):
        """Receive new state data for this light."""
        self._refresh(tradfri_device)
        self.async_schedule_update_ha_state()


class TradfriLight(Light):
    """The platform class required by Home Assistant."""

    def __init__(self, light, api):
        """Initialize a Light."""
        self._api = api
        self._light = None
        self._light_control = None
        self._light_data = None
        self._name = None
        self._features = SUPPORTED_FEATURES
        self._available = True

        self._refresh(light)

    @property
    def min_mireds(self):
        """Return the coldest color_temp that this light supports."""
        return self._light_control.min_mireds

    @property
    def max_mireds(self):
        """Return the warmest color_temp that this light supports."""
        return self._light_control.max_mireds

    @asyncio.coroutine
    def async_added_to_hass(self):
        """Start thread when added to hass."""
        self._async_start_observe()

    @property
    def available(self):
        """Return True if entity is available."""
        return self._available

    @property
    def should_poll(self):
        """No polling needed for tradfri light."""
        return False

    @property
    def supported_features(self):
        """Flag supported features."""
        return self._features

    @property
    def name(self):
        """Return the display name of this light."""
        return self._name

    @property
    def is_on(self):
        """Return true if light is on."""
        return self._light_data.state

    @property
    def brightness(self):
        """Return the brightness of the light."""
        return self._light_data.dimmer

    @property
    def color_temp(self):
        """Return the CT color value in mireds."""
        return self._light_data.color_temp

    @property
    def xy_color(self):
        """XY color of the light."""
        return self._light_data.xy_color

    @asyncio.coroutine
    def async_turn_off(self, **kwargs):
        """Instruct the light to turn off."""
        yield from self._api(self._light_control.set_state(False))

    @asyncio.coroutine
    def async_turn_on(self, **kwargs):
        """Instruct the light to turn on."""
        params = {}
        if ATTR_TRANSITION in kwargs:
            params[ATTR_TRANSITION_TIME] = int(kwargs[ATTR_TRANSITION]) * 10

        brightness = kwargs.get(ATTR_BRIGHTNESS)

        action = False

        if ATTR_XY_COLOR in kwargs:
            if brightness is not None:
                params.pop(ATTR_TRANSITION_TIME, None)
            yield from self._api(
                self._light_control.set_xy_color(*kwargs[ATTR_XY_COLOR],
                                                 **params))

        if ATTR_RGB_COLOR in kwargs:
            if brightness is not None:
                params.pop(ATTR_TRANSITION_TIME, None)
            xy = color_util.color_RGB_to_xy(*kwargs[ATTR_RGB_COLOR]))
            yield from self._api(
                self._light_control.set_xy_color(xy[0], xy[1]
                                                 **params))

        if ATTR_COLOR_TEMP in kwargs:
            if brightness is not None:
                params.pop(ATTR_TRANSITION_TIME, None)
            yield from self._api(
                self._light_control.set_color_temp(kwargs[ATTR_COLOR_TEMP],
                                                   **params))

        if brightness is not None:
            if brightness == 255:
                brightness = 254

            yield from self._api(
                self._light_control.set_dimmer(brightness,
                                               **params))
        else:
            yield from self._api(
                self._light_control.set_state(True))

    @callback
    def _async_start_observe(self, exc=None):
        """Start observation of light."""
        # pylint: disable=import-error
        from pytradfri.error import PytradfriError
        if exc:
            _LOGGER.warning("Observation failed for %s", self._name,
                            exc_info=exc)

        try:
            cmd = self._light.observe(callback=self._observe_update,
                                      err_callback=self._async_start_observe,
                                      duration=0)
            self.hass.async_add_job(self._api(cmd))
        except PytradfriError as err:
            _LOGGER.warning("Observation failed, trying again", exc_info=err)
            self._async_start_observe()

    def _refresh(self, light):
        """Refresh the light data."""
        self._light = light

        # Caching of LightControl and light object
        self._available = light.reachable
        self._light_control = light.light_control
        self._light_data = light.light_control.lights[0]
        self._name = light.name
        self._features = SUPPORTED_FEATURES

        if self._light_control.can_set_mireds:
            self._features |= SUPPORT_COLOR_TEMP
        if self._light_control.can_set_color:
            self._features |= SUPPORT_XY_COLOR
            self._features |= SUPPORT_RGB_COLOR

    @callback
    def _observe_update(self, tradfri_device):
        """Receive new state data for this light."""
        self._refresh(tradfri_device)
        self.async_schedule_update_ha_state()
