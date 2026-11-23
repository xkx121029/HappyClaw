"""AgentManager — process-wide singleton managing all HarnessAgent instances.

The implementation is split by responsibility across this package; every symbol
that used to live in this module is re-exported here, so existing imports of
``happyclaw.infra.agents.manager`` keep working unchanged.
"""

from __future__ import annotations

from happyclaw.infra.agents.manager.config import skill_package_ids_list as skill_package_ids_list
from happyclaw.infra.agents.manager.config import skills_disabled_set as skills_disabled_set
from happyclaw.infra.agents.manager.config import tools_disabled_set as tools_disabled_set
from happyclaw.infra.agents.manager.constants import (
    _HARNESS_AGENT_CONFIG_FIELDS as _HARNESS_AGENT_CONFIG_FIELDS,
)
from happyclaw.infra.agents.manager.core import (
    _AGENT_BOOT_START_TIMEOUT as _AGENT_BOOT_START_TIMEOUT,
)
from happyclaw.infra.agents.manager.core import AgentManager as AgentManager
from happyclaw.infra.agents.manager.create_spec import _CUSTOM_AGENT_ID_RE as _CUSTOM_AGENT_ID_RE
from happyclaw.infra.agents.manager.create_spec import _RESERVED_AGENT_IDS as _RESERVED_AGENT_IDS
from happyclaw.infra.agents.manager.create_spec import AgentCreateSpec as AgentCreateSpec
from happyclaw.infra.agents.manager.create_spec import _stored_id_list as _stored_id_list
from happyclaw.infra.agents.manager.create_spec import (
    validate_custom_agent_id as validate_custom_agent_id,
)
from happyclaw.infra.agents.manager.dsh import _dsh_local_roots as _dsh_local_roots
from happyclaw.infra.agents.manager.mcp import _bind_custom_mcp_tools as _bind_custom_mcp_tools
from happyclaw.infra.agents.manager.mcp import (
    _sanitize_bound_mcp_tools as _sanitize_bound_mcp_tools,
)
from happyclaw.infra.agents.manager.memory import _MEMORY_NS_PREFIX as _MEMORY_NS_PREFIX
from happyclaw.infra.agents.manager.memory import (
    _memory_aux_model_settings as _memory_aux_model_settings,
)
from happyclaw.infra.agents.manager.memory import (
    _memory_extract_settings as _memory_extract_settings,
)
from happyclaw.infra.agents.manager.memory import _memory_namespace as _memory_namespace
from happyclaw.infra.agents.manager.memory import _model_retry_on_failure as _model_retry_on_failure
from happyclaw.infra.agents.manager.memory import (
    _resolve_memory_backend_kwargs as _resolve_memory_backend_kwargs,
)
from happyclaw.infra.agents.manager.memory import (
    memory_extract_supported_options as memory_extract_supported_options,
)
from happyclaw.infra.agents.manager.reload import (
    _AGENT_STATES_NEEDING_MODEL_RELOAD as _AGENT_STATES_NEEDING_MODEL_RELOAD,
)
from happyclaw.infra.agents.manager.reload import (
    _PROVIDER_RELOAD_CONCURRENCY as _PROVIDER_RELOAD_CONCURRENCY,
)
from happyclaw.infra.agents.manager.startup import (
    _fill_missing_subagent_colors as _fill_missing_subagent_colors,
)
