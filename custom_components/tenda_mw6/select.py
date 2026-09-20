from __future__ import annotations

from homeassistant.components.select import DOMAIN as SELECT_DOMAIN, SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import DOMAIN

SORT_OPTIONS = ["Urządzenie", "IP", "Download", "Upload"]
UNIT_OPTIONS = ["MB", "GB"]

SELECT_ENTITY_IDS = {
    "dashboard_sort": f"{SELECT_DOMAIN}.tenda_mw6_sortowanie",
    "transfer_unit": f"{SELECT_DOMAIN}.tenda_mw6_transfer_unit",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up dashboard preference selectors."""
    registry = er.async_get(hass)

    # Version 1.3.0 used an ignored private attribute for the suggested object
    # id. Rename those registry entries before adding the entities so existing
    # installations receive the documented, stable IDs automatically.
    for unique_suffix, target_entity_id in SELECT_ENTITY_IDS.items():
        unique_id = f"{entry.entry_id}_{unique_suffix}"
        current_entity_id = registry.async_get_entity_id(
            SELECT_DOMAIN, DOMAIN, unique_id
        )
        if (
            current_entity_id is not None
            and current_entity_id != target_entity_id
            and registry.async_get(target_entity_id) is None
        ):
            registry.async_update_entity(
                current_entity_id, new_entity_id=target_entity_id
            )

    async_add_entities(
        [
            TendaMW6PreferenceSelect(
                entry=entry,
                unique_suffix="dashboard_sort",
                entity_id=SELECT_ENTITY_IDS["dashboard_sort"],
                name="Dashboard sorting",
                icon="mdi:sort",
                options=SORT_OPTIONS,
                default="Urządzenie",
            ),
            TendaMW6PreferenceSelect(
                entry=entry,
                unique_suffix="transfer_unit",
                entity_id=SELECT_ENTITY_IDS["transfer_unit"],
                name="Transfer display unit",
                icon="mdi:database",
                options=UNIT_OPTIONS,
                default="MB",
            ),
        ]
    )


class TendaMW6PreferenceSelect(SelectEntity, RestoreEntity):
    """A restored dashboard preference owned by the MW6 integration."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        entry: ConfigEntry,
        unique_suffix: str,
        entity_id: str,
        name: str,
        icon: str,
        options: list[str],
        default: str,
    ) -> None:
        self._entry = entry
        self.entity_id = entity_id
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_options = options
        self._attr_current_option = default

    async def async_added_to_hass(self) -> None:
        """Restore the last selected option."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in self.options:
            self._attr_current_option = last_state.state

    async def async_select_option(self, option: str) -> None:
        """Select and persist one dashboard preference."""
        if option not in self.options:
            raise ValueError(f"Unsupported option: {option}")
        self._attr_current_option = option
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Tenda MW6",
            manufacturer="Tenda",
            model="Nova MW6",
        )
