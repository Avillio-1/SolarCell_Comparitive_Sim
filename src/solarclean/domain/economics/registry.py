from __future__ import annotations

from dataclasses import dataclass, field

from solarclean.domain.economics.contracts import CostCategory, CostComponent


@dataclass(frozen=True)
class RegisteredCostComponent:
    scenario_name: str
    component: CostComponent


@dataclass
class CostComponentRegistry:
    """Small registry for scenario cost components with units and sources."""

    _items: list[RegisteredCostComponent] = field(default_factory=list)

    def add(self, scenario_name: str, component: CostComponent) -> None:
        if not scenario_name:
            raise ValueError("scenario_name must not be empty.")
        self._items.append(
            RegisteredCostComponent(
                scenario_name=scenario_name,
                component=component,
            )
        )

    def components_for(
        self,
        scenario_name: str,
        category: CostCategory | None = None,
    ) -> tuple[CostComponent, ...]:
        components: list[CostComponent] = []

        for item in self._items:
            if item.scenario_name != scenario_name:
                continue
            if category is not None and item.component.category != category:
                continue
            components.append(item.component)

        return tuple(components)

    def all_items(self) -> tuple[RegisteredCostComponent, ...]:
        return tuple(self._items)
