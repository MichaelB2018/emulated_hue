"""Config flow for the Emulated Hue integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithConfigEntry,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_ADVERTISE_PORT,
    CONF_ENTITIES,
    CONF_ENTITY_NAME,
    CONF_LISTEN_PORT,
    DEFAULT_LISTEN_PORT,
    DOMAIN,
    SUPPORTED_DOMAINS,
)


class EmulatedHueConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Emulated Hue."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> EmulatedHueOptionsFlow:
        """Get the options flow for this handler."""
        return EmulatedHueOptionsFlow(config_entry)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial setup step (manual UI flow)."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}

        if user_input is not None:
            port = int(user_input[CONF_LISTEN_PORT])
            if not 1024 <= port <= 65535:
                errors[CONF_LISTEN_PORT] = "invalid_port"
            else:
                adv_port = int(
                    user_input.get(CONF_ADVERTISE_PORT, port)
                )
                return self.async_create_entry(
                    title="Emulated Hue",
                    data={
                        CONF_LISTEN_PORT: port,
                        CONF_ADVERTISE_PORT: adv_port,
                    },
                    options={CONF_ENTITIES: {}},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LISTEN_PORT, default=DEFAULT_LISTEN_PORT
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1024,
                            max=65535,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_ADVERTISE_PORT, default=80
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=65535,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
            errors=errors,
        )


class EmulatedHueOptionsFlow(OptionsFlowWithConfigEntry):
    """Handle options for Emulated Hue."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Manage the entity selection."""
        if user_input is not None:
            selected_entities: list[str] = user_input.get(CONF_ENTITIES, [])
            port: int = int(user_input.get(
                CONF_LISTEN_PORT, DEFAULT_LISTEN_PORT
            ))
            adv_port: int = int(user_input.get(
                CONF_ADVERTISE_PORT, port
            ))

            # Preserve existing custom names for entities that are still selected
            existing: dict[str, dict[str, str]] = self.options.get(
                CONF_ENTITIES, {}
            )
            new_entities: dict[str, dict[str, str]] = {}
            for entity_id in selected_entities:
                if entity_id in existing:
                    new_entities[entity_id] = existing[entity_id]
                else:
                    new_entities[entity_id] = {CONF_ENTITY_NAME: ""}

            # Store temporarily and move to name editing step
            self._new_entities = new_entities
            self._new_port = port
            self._new_advertise_port = adv_port
            return await self.async_step_entity_names()

        # Build list of currently selected entity IDs
        current_entities: list[str] = list(
            self.options.get(CONF_ENTITIES, {}).keys()
        )
        current_port: int = self.config_entry.data.get(
            CONF_LISTEN_PORT, DEFAULT_LISTEN_PORT
        )
        current_adv_port: int = self.config_entry.data.get(
            CONF_ADVERTISE_PORT, current_port
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LISTEN_PORT, default=current_port
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1024,
                            max=65535,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_ADVERTISE_PORT, default=current_adv_port
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=65535,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_ENTITIES, default=current_entities
                    ): EntitySelector(
                        EntitySelectorConfig(
                            domain=list(SUPPORTED_DOMAINS),
                            multiple=True,
                        )
                    ),
                }
            ),
        )

    async def async_step_entity_names(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Set custom names for selected entities."""
        if user_input is not None:
            # Update names from user input
            for entity_id, entity_conf in self._new_entities.items():
                key = entity_id.replace(".", "_")
                name = user_input.get(key, "")
                entity_conf[CONF_ENTITY_NAME] = name

            # Update the port in data and entities in options
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    CONF_LISTEN_PORT: self._new_port,
                    CONF_ADVERTISE_PORT: self._new_advertise_port,
                },
            )

            return self.async_create_entry(
                title="",
                data={CONF_ENTITIES: self._new_entities},
            )

        # Build a schema with one text field per entity for the custom name
        ent_reg = er.async_get(self.hass)
        schema_dict: dict[vol.Optional, Any] = {}

        for entity_id, entity_conf in self._new_entities.items():
            current_name = entity_conf.get(CONF_ENTITY_NAME, "")
            friendly_name = entity_id
            entry = ent_reg.async_get(entity_id)
            if entry and entry.name:
                friendly_name = entry.name
            elif entry and entry.original_name:
                friendly_name = entry.original_name

            key = entity_id.replace(".", "_")
            schema_dict[
                vol.Optional(key, default=current_name or friendly_name)
            ] = TextSelector(TextSelectorConfig())

        return self.async_show_form(
            step_id="entity_names",
            data_schema=vol.Schema(schema_dict),
        )
