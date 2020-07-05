"""Platform for sensor integration."""
import async_timeout
import json
import logging
import voluptuous as vol

from datetime import timedelta

import homeassistant.helpers.config_validation as cv

from homeassistant.const import (
    ATTR_ATTRIBUTION,
    ATTR_TIME,
    ATTR_UNIT_OF_MEASUREMENT,
    ATTR_LOCATION,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    CONF_MONITORED_CONDITIONS,
    DEVICE_CLASS_HUMIDITY,
    DEVICE_CLASS_TEMPERATURE,
    TEMP_CELSIUS,
    HTTP_BAD_REQUEST,
    UNIT_PERCENTAGE,
)
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

CONF_STATION = "station"

SENSOR_TYPES = {
    "temperature": ["Temperature", TEMP_CELSIUS, DEVICE_CLASS_TEMPERATURE],
    "precipitation": ["Precipitation", "mm", None],
    "humidity": ["Humidity", UNIT_PERCENTAGE, DEVICE_CLASS_HUMIDITY],
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_STATION, default="Arosa"): cv.string,
        vol.Optional(CONF_MONITORED_CONDITIONS, default=["temperature"]): vol.All(
            cv.ensure_list, vol.Length(min=1), [vol.In(SENSOR_TYPES)]
        ),
    }
)

CONFIG_CONDITIONS = {
    "temperature": {
        "url": "https://data.geo.admin.ch/ch.meteoschweiz.messwerte-lufttemperatur-10min/ch.meteoschweiz.messwerte-lufttemperatur-10min_de.json"
    },
    "precipitation": {
        "url": "https://data.geo.admin.ch/ch.meteoschweiz.messwerte-niederschlag-10min/ch.meteoschweiz.messwerte-niederschlag-10min_de.json"
    },
    "humidity": {
        "url": "https://data.geo.admin.ch/ch.meteoschweiz.messwerte-luftfeuchtigkeit-10min/ch.meteoschweiz.messwerte-luftfeuchtigkeit-10min_de.json"
    },
}


async def async_setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the sensor platform."""
    async def async_update_data():
        data = {}
        for mon_cond, config in CONFIG_CONDITIONS.items():
            url = config["url"]
            urlparams = ""
            websession = async_get_clientsession(hass)
            with async_timeout.timeout(10):
                resp = await websession.get(url, params=urlparams)
            if resp.status >= HTTP_BAD_REQUEST:
                return
            text = await resp.text()
            raw_data = json.loads(text)
            for entry in raw_data["features"]:
                station = entry["properties"]["station_name"]
                unit = entry["properties"]["unit"]
                coordinates = entry["geometry"]["coordinates"]
                time = entry["properties"]["reference_ts"]
                value = entry["properties"]["value"]
                if station not in data:
                    data[station] = {
                        "coordinates": coordinates,
                    }
                data[station][mon_cond] = {
                    "value": value,
                    "unit": unit,
                    "time": time,
                }
        return data

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="MeteoSwissData",
        update_method=async_update_data,
        update_interval=timedelta(minutes=10),
    )
    await coordinator.async_refresh()
    station = config.get(CONF_STATION)
    monitored_conditions = config.get("monitored_conditions")
    entities = []
    for condition in monitored_conditions:
        entities.append(MeteoSwissSensor(coordinator, condition, station))
    add_entities(entities)


class MeteoSwissSensor(Entity):
    """Representation of a Sensor."""

    def __init__(self, coordinator, monitored_condition, station):
        """Initialize the sensor."""
        self._state = None
        self._coordinator = coordinator
        self._monitored_condition = monitored_condition
        self._station = station

    @property
    def name(self):
        """Return the name of the sensor."""
        return "meteoswiss_" + self._monitored_condition

    @property
    def should_poll(self):
        """No need to poll. Coordinator notifies entity of updates."""
        return False

    @property
    def available(self):
        """Return if entity is available."""
        return self._coordinator.last_update_success

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._coordinator.data[self._station][self._monitored_condition]["value"]

    @property
    def device_state_attributes(self):
        """Return device attributes."""
        attributes = {
            ATTR_ATTRIBUTION: "Data provided by MeteoSwiss via data.geo.admin.ch.",
            ATTR_TIME: self._coordinator.data[self._station][self._monitored_condition][
                "time"
            ],
            ATTR_UNIT_OF_MEASUREMENT: self._coordinator.data[self._station][
                self._monitored_condition
            ]["unit"],
            ATTR_LOCATION: self._station,
            ATTR_LATITUDE: self._coordinator.data[self._station]["coordinates"][0],
            ATTR_LONGITUDE: self._coordinator.data[self._station]["coordinates"][1],
        }
        return attributes

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._coordinator.data[self._station][self._monitored_condition]["unit"]

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self.async_write_ha_state)
        )

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        await self._coordinator.async_request_refresh()
