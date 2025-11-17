import dataclasses
import time
from typing import (Any, Callable, Dict, Optional, Tuple, Type, TypeVar, Union,
                    get_args, get_origin)

from ocs import ocs_agent

ActionResultType = Optional[Dict[str, Any]]
OcsOpReturnType = Tuple[bool, str]


@dataclasses.dataclass
class BaseAction:
    """
    Base subclass for actions that correspond to OCS tasks. Such actions can
    be used to generate a generic task that creates the action, passes
    to some callback function, and waits until the action is resolved before
    returning.
    """

    def __post_init__(self) -> None:
        self._session_data: Dict[str, Any] = {}
        self._processed: bool = False
        self._success: bool = False
        self._traceback: Optional[str] = None
        self._return_message: Optional[str] = None

    def resolve_action(
        self,
        success: bool,
        traceback: Optional[str] = None,
        return_message: Optional[str] = None,
    ) -> None:
        """
        Resolves an action, signifying it has been completed. Tasks waiting for
        this action to be resolved can then return.
        """
        self._success = success
        if traceback is not None:
            self._traceback = traceback
        if return_message is not None:
            self._return_message = return_message
        self._processed = True

    def update_session_data(self, data: Dict[str, Any]):
        self._session_data.update(data)

    def sleep_until_resolved(self, session: ocs_agent.OpSession, interval=0.2) -> None:
        """
        Sleeps until the action has been resolved.
        """
        while not self._processed:
            session.data = self._session_data
            time.sleep(interval)

        session.data = self._session_data


def _is_instanceable(t: Type) -> bool:
    """
    Checks if its possible to run isinstance with a specified type. This is
    needed because older version of python don't let you run this on subscripted
    generics.
    """
    try:
        isinstance(0, t)
        return True
    except Exception:
        return False


def _get_param_type(t: Type) -> Optional[Type]:
    """
    OCS param type variables require you to be able to run isinstance,
    which does not work for subscripted generics like Optional in python3.8.
    This function attempts to convert types to values that will be accepted
    by ocs_agent.param, unwrapping optional types if we are unable to run
    isinstance off the bat.

    Other subscripted generics such as List[...] or Dict[...] are not currently
    supported.

    This function will return the unwrapped type, or None if it fails.
    """
    origin_type = get_origin(t)

    # Unwrap possible option type
    if origin_type == Union:
        sub_types = get_args(t)
        if len(sub_types) != 2:
            return None
        if type(None) not in sub_types:
            return None
        for st in sub_types:
            if st is not type(None):
                if _is_instanceable(st):
                    return st

    elif _is_instanceable(t):
        # If this works, then it should work with ocs_agent.param
        return t

    return None


BaseActionT = TypeVar("BaseActionT", bound=BaseAction)


def register_task_from_action(
    agent: ocs_agent.OCSAgent,
    name: str,
    action_class: Type[BaseActionT],
    callback: Callable[[BaseActionT], Any],
) -> None:
    """
    Registers a generic OCS task based on an Action dataclass. This will
    automatically set OCS parameters, and the docstrings based on the dataclass
    fields and the Action class docstrings.

    The generic task will always do the following:
     - generate an instance of the action class based on passed in params
     - pass the action to the supplied callback function
     - wait until the action is resolved by the agent, regularly updating
       session.data.
     - If the action is resolved successfully, will return a successful result.
       If the action failed, this will log the action traceback if it is set,
       and return a failed result.

    Args
    --------
    agent: OCSAgent
        OCS agent to use to register the task
    name: str
        Name of the task. This will be used to set the operation endpoint.
    action_class: Type[BaseActionT]
        The class to be used to generate the task.
    callback: Callable[[BaseActionT], Any]
        Function to call with the action instance after it is created.
        It is expected that after calling this, the task will eventually
        be processed and resolved by the agent.
    """

    def task(
        session: ocs_agent.OpSession, params: Optional[Dict[str, Any]] = None
    ) -> OcsOpReturnType:
        _params: Dict[str, Any] = {} if params is None else params
        action: BaseActionT = action_class(**_params)
        callback(action)
        action.sleep_until_resolved(session)

        if action._success:
            if action._return_message is None:
                return_message = f"{name} successful"
            else:
                return_message = action._return_message
            return True, return_message

        else:
            if action._return_message is None:
                return_message = f"{name} failed"
            else:
                return_message = action._return_message

            if action._traceback is not None:
                agent.log.error("traceback:\n{traceback}", traceback=action._traceback)

            return False, return_message

    task.__doc__ = action_class.__doc__

    # Adds ocs parameters
    for f in dataclasses.fields(action_class):
        param_type = _get_param_type(f.type)
        if param_type is None:
            raise ValueError(f"Unsupported param type for arg {f.name}: {f.type}")
        param_kwargs: Dict[str, Any] = {
            "type": param_type,
        }
        if f.default != dataclasses.MISSING:
            param_kwargs["default"] = f.default
        if isinstance(f.metadata, dict):
            param_kwargs.update(f.metadata.get("ocs_param_kwargs", {}))
        task = ocs_agent.param(f.name, **param_kwargs)(task)

    agent.register_task(name, task)
