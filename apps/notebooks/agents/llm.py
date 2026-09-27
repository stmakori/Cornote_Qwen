"""Claude tool-use loop for Cornote's agents.

No separate agent framework: this is a plain loop on top of the `anthropic`
SDK (same client construction as `services/ai_service.py`). Each turn, Claude
either calls one or more tools from `tools.py` or gives a final answer; tool
results are fed back until it's done or the call budget runs out.
"""
import logging

from django.conf import settings

from ..services.ai_service import _get_client
from .tools import TOOL_SPECS, build_tools

logger = logging.getLogger(__name__)


class AgentUnavailable(Exception):
    """Claude could not complete this run."""


def _model():
    return getattr(settings, 'AGENT_MODEL_ID', '') or settings.ANTHROPIC_MODEL_ID


def _tool_result_content(output) -> str:
    return output if isinstance(output, str) else str(output)


def run_agent(ctx, system_prompt, prompt, tool_names):
    """Run one agent task to completion. Returns (final_text, provider_label)."""
    if not getattr(settings, 'ANTHROPIC_API_KEY', ''):
        raise AgentUnavailable('No AI provider configured. Set ANTHROPIC_API_KEY in .env.')

    label = f'Claude ({_model()})'
    tools = dict(zip(tool_names, build_tools(ctx, tool_names)))
    tool_specs = [TOOL_SPECS[name] for name in tool_names]
    messages = [{'role': 'user', 'content': prompt}]
    max_turns = int(getattr(settings, 'AGENT_MAX_TOOL_CALLS', 10)) + 2

    client = _get_client()
    try:
        for _ in range(max_turns):
            response = client.messages.create(
                model=_model(),
                max_tokens=2000,
                system=system_prompt,
                messages=messages,
                tools=tool_specs,
            )
            messages.append({'role': 'assistant', 'content': response.content})

            tool_uses = [block for block in response.content if getattr(block, 'type', None) == 'tool_use']
            if not tool_uses:
                text = ''.join(
                    getattr(block, 'text', '') for block in response.content if getattr(block, 'type', None) == 'text'
                ).strip()
                if not text:
                    raise ValueError('Claude returned an empty answer.')
                return text, label

            results = []
            for block in tool_uses:
                fn = tools.get(block.name)
                if fn is None:
                    output = f'Unknown tool: {block.name}'
                else:
                    try:
                        output = fn(**(block.input or {}))
                    except Exception as exc:  # noqa: BLE001 - surface the error to Claude, don't crash the run
                        output = f'Tool error: {exc}'
                results.append({
                    'type': 'tool_result',
                    'tool_use_id': block.id,
                    'content': _tool_result_content(output),
                })
            messages.append({'role': 'user', 'content': results})

        raise AgentUnavailable('Claude used too many tool calls without finishing.')
    except AgentUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - any failure here ends the run
        logger.warning('Agent run failed: %s', exc)
        ctx.steps.append({'tool': 'provider_error', 'input': label, 'result': str(exc)[:200]})
        raise AgentUnavailable(f'Claude failed: {exc}') from exc
    finally:
        if hasattr(client, 'close'):
            client.close()
