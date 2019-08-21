"""
Support for SolarEdge Monitoring API.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/sensor.solaredge_local/
"""
import logging
from datetime import timedelta, datetime

from requests.exceptions import HTTPError, ConnectTimeout
from solaredge_local import SolarEdge
import voluptuous as vol


from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import CONF_IP_ADDRESS, CONF_NAME, POWER_WATT, ENERGY_WATT_HOUR, TEMP_CELSIUS 
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

DOMAIN = "solaredge_local"
UPDATE_DELAY = timedelta(seconds=10)

# Supported sensor types:
# Key: ['json_key', 'name', unit, icon]
SENSOR_TYPES = {
    "lifetime_energy": [
        "energyTotal",
        "Lifetime energy",
        ENERGY_WATT_HOUR,
        "mdi:solar-power",
    ],
    "energy_this_year": [
        "energyThisYear",
        "Energy this year",
        ENERGY_WATT_HOUR,
        "mdi:solar-power",
    ],
    "energy_this_month": [
        "energyThisMonth",
        "Energy this month",
        ENERGY_WATT_HOUR,
        "mdi:solar-power",
    ],
    "energy_today": [
        "energyToday",
        "Energy today",
        ENERGY_WATT_HOUR,
        "mdi:solar-power",
    ],
    "current_power": ["currentPower", "Current Power", POWER_WATT, "mdi:solar-power"],
    "inverter_status": ["inverterStatus", "Inverter status", '', ""],
    "inverter_voltage": ["inverterVoltage", "Inverter voltage", POWER_WATT, "mdi:current-dc"],
    "inverter_temperature": ["inverterTemperature", "Inverter temperature", TEMP_CELSIUS , "mdi:thermometer"],
    "optimizer_status": ["optimizerStatus", "Optimizer status", 'online', ""],
    "grid_frequency": ["gridFrequency", "Grid frequency", 'Hz', "mdi:current-ac"],
    "grid_voltage": ["gridVoltage", "Grid voltage", 'V', "mdi:power-plug"],    
    "optimizerStatus": ["optimizerData", "Optimizers", '', ""],    
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_IP_ADDRESS): cv.string,
        vol.Optional(CONF_NAME, default="SolarEdge"): cv.string,
    }
)

_LOGGER = logging.getLogger(__name__)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Create the SolarEdge Monitoring API sensor."""
    ip_address = config[CONF_IP_ADDRESS]
    platform_name = config[CONF_NAME]

    # Create new SolarEdge object to retrieve data
    api = SolarEdge("http://{}/".format(ip_address))

    # Check if api can be reached and site is active
    try:
        status = api.get_status()

        status.energy  # pylint: disable=pointless-statement
        _LOGGER.debug("Credentials correct and site is active")
    except AttributeError:
        _LOGGER.error("Missing details data in solaredge response")
        _LOGGER.debug("Response is: %s", status)
        return
    except (ConnectTimeout, HTTPError):
        _LOGGER.error("Could not retrieve details from SolarEdge API")
        return

    # Create solaredge data service which will retrieve and update the data.
    data = SolarEdgeData(hass, api)

    # Create a new sensor for each sensor type.
    entities = []
    for sensor_key in SENSOR_TYPES:
        if(sensor_key != 'optimizerStatus'):
            sensor = SolarEdgeSensor(platform_name, sensor_key, data)
        else:            
            sensor = SolarEdgeOptimizerSensor(platform_name, sensor_key, data)
        entities.append(sensor)

    add_entities(entities, True)

class SolarEdgeOptimizerSensor(Entity):
    """Representation of an SolarEdge Monitoring API sensor."""

    def __init__(self, platform_name, sensor_key, data):
        """Initialize the sensor."""
        self.platform_name = platform_name
        self.sensor_key = sensor_key
        self.data = data
        self._state = None    
        self._attributes = None
        self._unit_of_measurement = SENSOR_TYPES[self.sensor_key][2]

    @property
    def name(self):
        """Return the name."""
        return "{} ({})".format(self.platform_name, SENSOR_TYPES[self.sensor_key][1])

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def icon(self):
        """Return the sensor icon."""
        return SENSOR_TYPES[self.sensor_key][3]

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state
    
    @property
    def device_state_attributes(self):
        """Return device specific state attributes."""
        return self._attributes         

    def update(self):
        """Get the latest data from the sensor and update the state."""
        self.data.updateOptimizers()
        self._state = len(self.data.optimizerData)
        self._attributes = {}
        for optimizer in self.data.optimizerData:
           self._attributes[optimizer.serial] = optimizer
        
    
class SolarEdgeSensor(Entity):
    """Representation of an SolarEdge Monitoring API sensor."""

    def __init__(self, platform_name, sensor_key, data):
        """Initialize the sensor."""
        self.platform_name = platform_name
        self.sensor_key = sensor_key
        self.data = data
        self._state = None

        self._json_key = SENSOR_TYPES[self.sensor_key][0]
        self._unit_of_measurement = SENSOR_TYPES[self.sensor_key][2]

    @property
    def name(self):
        """Return the name."""
        return "{} ({})".format(self.platform_name, SENSOR_TYPES[self.sensor_key][1])

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def icon(self):
        """Return the sensor icon."""
        return SENSOR_TYPES[self.sensor_key][3]

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    def update(self):
        """Get the latest data from the sensor and update the state."""
        self.data.update()
        self._state = self.data.data[self._json_key]


class SolarEdgeData:
    """Get and update the latest data."""

    def __init__(self, hass, api):
        """Initialize the data object."""
        self.hass = hass
        self.api = api
        self.data = {}
        self.optimizerData = []

    def getStatusText(self,value):        
      return {
          0: 'Shutdown',
          1: 'Error',
          2: 'Standby',
          3: 'Pairing',
          4: 'Production',
          5: 'AC Charging',
          6: 'Not paired',
          7: 'Nightmode',
          8: 'Grid monitoring',
          9: 'IDLE',
      }.get(value, 'unknown')


    @Throttle(UPDATE_DELAY)
    def update(self):
        """Update the data from the SolarEdge Monitoring API."""
        try:
            response = self.api.get_status()
            _LOGGER.debug("response from SolarEdge: %s", response) 
        except (ConnectTimeout):
            _LOGGER.error("Connection timeout, skipping update")
            return        
        except (HTTPError):
            _LOGGER.error("Could not retrieve data, skipping update")
            return
        
        try:       
            self.data["energyTotal"] = response.energy.total
            self.data["energyThisYear"] = response.energy.thisYear
            self.data["energyThisMonth"] = response.energy.thisMonth
            self.data["energyToday"] = response.energy.today
            self.data["currentPower"] = response.powerWatt
            self.data["inverterVoltage"] = response.inverters.primary.voltage
            self.data["inverterTemperature"] = response.inverters.primary.temperature.value
            self.data["optimizerStatus"] = str(response.optimizersStatus.online) + '/'+ str(response.optimizersStatus.total)
            self.data["gridFrequency"] = response.frequencyHz
            self.data["gridVoltage"] = response.voltage          
            
            self.data["inverterStatus"] = self.getStatusText(response.status)
            
            _LOGGER.debug("Updated SolarEdge overview data: %s", self.data)
        except AttributeError:
            _LOGGER.error("Missing details data in SolarEdge response")

    @Throttle(UPDATE_DELAY)
    def updateOptimizers(self):      
        """Update the data from the SolarEdge Monitoring API."""
        try:
            optimizersResponse = self.api.get_optimizers()
            _LOGGER.debug("response from SolarEdge: %s", optimizersResponse) 
        except (ConnectTimeout):
            _LOGGER.error("Connection timeout, skipping update")
            return        
        except (HTTPError):
            _LOGGER.error("Could not retrieve data, skipping update")
            return        
        try:       
            self.optimizerData = []
            for optimizer in optimizersResponse.diagnostics.inverters.primary.optimizer:
                currentOptimizer={}
                currentOptimizer["serial"] = optimizer.serialNumber
                currentOptimizer["inputC"] = datetime(optimizer.lastReport.year, optimizer.lastReport.month, optimizer.lastReport.day, optimizer.lastReport.hour, optimizer.lastReport.minute, optimizer.lastReport.second)
                currentOptimizer["outputV"] = optimizer.outputV
                currentOptimizer["inputV"] = optimizer.inputV
                currentOptimizer["inputC"] = optimizer.inputC
                currentOptimizer["inputW"] = optimizer.inputV* optimizer.inputC
                currentOptimizer["temperature"] = optimizer.temperature.value
                self.optimizerData.append(currentOptimizer)            
            _LOGGER.debug("Updated SolarEdge overview data: %s", self.optimizerData)
        except AttributeError:
            _LOGGER.error("Missing details data in SolarEdge response")            
