import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import scs9009, uart
from esphome.const import CONF_ID

AUTO_LOAD = ["scs9009"]
DEPENDENCIES = ["uart"]

andy_scs9009_ns = cg.esphome_ns.namespace("andy_scs9009")
AndySCS9009Component = andy_scs9009_ns.class_(
    "AndySCS9009Component", scs9009.SCS9009Component
)

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(AndySCS9009Component),
    }
).extend(uart.UART_DEVICE_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    await uart.register_uart_device(var, config)
