# src/omniforge_host/state/store.py
from __future__ import annotations

import asyncio
from typing import Callable, Awaitable
from omniforge_api.actions import BaseAction
from omniforge_host.state.state_types import AppState
from omniforge_host.state.reducers import root_reducer

Subscriber = Callable[[AppState, set[str]], Awaitable[None]] # Теперь передает changed_keys

class Store:
    def __init__(self, initial_state: AppState) -> None:
        self._state = initial_state
        self._subscribers: list[Subscriber] = []
        self._lock = asyncio.Lock()
        self._is_dispatching = False

    @property
    def state(self) -> AppState:
        return self._state

    async def dispatch(self, action: BaseAction) -> None:
        if self._is_dispatching:
            raise RuntimeError("Cannot dispatch an action while another action is being dispatched.")
        
        self._is_dispatching = True
        try:
            old_state = self._state
            
            try:
                new_state = root_reducer(self._state, action)
            except Exception as e:
                import structlog
                log = structlog.get_logger("store")
                log.error(f"CRITICAL: Reducer crashed on action {action}", exc_info=e)
                raise e
            
            if new_state is not old_state:
                # Вычисляем изменившиеся ключи верхнего уровня
                changed_keys: set[str] = set()
                for key in AppState.model_fields:
                    if getattr(new_state, key) is not getattr(old_state, key):
                        changed_keys.add(key)
                
                self._state = new_state
                # Сначала выключаем флаг, чтобы подписчики могли делать новые dispatch!
                self._is_dispatching = False
                
                await self._notify_subscribers(changed_keys)
        finally:
            self._is_dispatching = False
            

    def subscribe(self, subscriber: Subscriber) -> Callable[[], None]:
        self._subscribers.append(subscriber)
        def unsubscribe() -> None:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)
        return unsubscribe

    async def _notify_subscribers(self, changed_keys: set[str]) -> None:
        tasks = [subscriber(self._state, changed_keys) for subscriber in self._subscribers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                import structlog
                log = structlog.get_logger("store")
                log.error("Subscriber notification failed", exc_info=result)