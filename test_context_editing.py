"""
Test Anthropic's context editing with server-side tools (web_search).

This script verifies whether server-side tool results (like web_search)
are subject to the same context clearing as client-side tools.

Key insight: web_search is a SERVER-SIDE tool where:
- The API executes the search internally
- Results come back as `server_tool_use` and `web_search_tool_result` blocks
- You pass back the full assistant response in multi-turn conversations
"""

import anthropic
import json


def print_context_management(response, prefix=""):
    """Helper to print context management info from response."""
    if hasattr(response, 'context_management') and response.context_management:
        cm = response.context_management
        if isinstance(cm, dict):
            print(f"{prefix}Context management applied:")
            print(f"{prefix}  {json.dumps(cm, indent=2)}")
        else:
            # Handle object-style response
            print(f"{prefix}Context management applied: {cm}")
        return True
    return False


def test_context_editing_with_web_search():
    """
    Test that web_search results are cleared by context editing.

    Strategy:
    1. Make multiple turns with web_search to build up context
    2. Set a low trigger threshold (5000 tokens)
    3. Check if clearing is applied to server-side tool results
    """
    client = anthropic.Anthropic()

    # Context management configuration - low threshold to trigger clearing
    context_mgmt = {
        "edits": [
            {
                "type": "clear_tool_uses_20250919",
                "trigger": {
                    "type": "input_tokens",
                    "value": 5000  # Very low threshold to trigger clearing quickly
                },
                "keep": {
                    "type": "tool_uses",
                    "value": 1  # Keep only the most recent tool use
                }
            }
        ]
    }

    tool_definition = {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": 3
    }

    messages = []
    search_topics = [
        "Python 3.13 new features",
        "TypeScript 5.5 release",
        "Rust programming language updates 2025",
        "Go language generics improvements"
    ]

    for i, topic in enumerate(search_topics):
        print(f"\n{'='*60}")
        print(f"Turn {i+1}: Searching for '{topic}'")
        print('='*60)

        messages.append({
            "role": "user",
            "content": f"Search for: {topic}"
        })

        response = client.beta.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1024,
            messages=messages,
            tools=[tool_definition],
            betas=["context-management-2025-06-27"],
            context_management=context_mgmt
        )

        print(f"Stop reason: {response.stop_reason}")
        print(f"Input tokens: {response.usage.input_tokens}")
        print(f"Output tokens: {response.usage.output_tokens}")

        # Check for server tool use
        if hasattr(response.usage, 'server_tool_use'):
            print(f"Server tool use: {response.usage.server_tool_use}")

        # Check if context management was applied
        if print_context_management(response):
            print("\n*** SERVER-SIDE TOOL RESULTS WERE CLEARED! ***")
        else:
            print("No context management applied yet (under threshold)")

        # Add assistant response to messages for next turn
        # This includes server_tool_use and web_search_tool_result blocks
        # Filter out empty text blocks which cause API errors
        filtered_content = [
            block for block in response.content
            if not (hasattr(block, 'type') and block.type == 'text' and hasattr(block, 'text') and not block.text.strip())
        ]
        messages.append({"role": "assistant", "content": filtered_content})

        # Show content block types in response
        print(f"\nResponse content blocks:")
        for j, block in enumerate(response.content):
            block_type = block.type if hasattr(block, 'type') else type(block).__name__
            print(f"  [{j}] {block_type}")

    print(f"\n{'='*60}")
    print("Final message count:", len(messages))
    print('='*60)


def test_exclude_tools():
    """
    Test that exclude_tools prevents web_search from being cleared.
    """
    client = anthropic.Anthropic()

    print("\n" + "="*60)
    print("Testing exclude_tools=['web_search']")
    print("="*60)

    # Build up context first
    messages = []
    for topic in ["AI news", "Machine learning trends"]:
        messages.append({"role": "user", "content": f"Search for: {topic}"})
        response = client.beta.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1024,
            messages=messages,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            betas=["context-management-2025-06-27"],
            context_management={
                "edits": [
                    {
                        "type": "clear_tool_uses_20250919",
                        "trigger": {"type": "input_tokens", "value": 5000},
                        "keep": {"type": "tool_uses", "value": 1},
                        "exclude_tools": ["web_search"]  # Exclude from clearing
                    }
                ]
            }
        )
        filtered_content = [
            block for block in response.content
            if not (hasattr(block, 'type') and block.type == 'text' and hasattr(block, 'text') and not block.text.strip())
        ]
        messages.append({"role": "assistant", "content": filtered_content})
        print(f"Input tokens: {response.usage.input_tokens}")

        if print_context_management(response, "  "):
            print("  (web_search should NOT be in cleared tools)")
        else:
            print("  No context management applied (excluded or under threshold)")


def test_comparison():
    """
    Compare behavior WITH and WITHOUT exclude_tools.
    """
    client = anthropic.Anthropic()

    print("\n" + "="*60)
    print("Comparison: With vs Without exclude_tools")
    print("="*60)

    topics = ["quantum computing news", "blockchain updates", "cloud computing trends"]

    for exclude in [False, True]:
        print(f"\n--- exclude_tools={'[\"web_search\"]' if exclude else 'None'} ---")
        messages = []

        edits_config = {
            "type": "clear_tool_uses_20250919",
            "trigger": {"type": "input_tokens", "value": 5000},
            "keep": {"type": "tool_uses", "value": 1}
        }
        if exclude:
            edits_config["exclude_tools"] = ["web_search"]

        for topic in topics:
            messages.append({"role": "user", "content": f"Search: {topic}"})
            response = client.beta.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=512,
                messages=messages,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                betas=["context-management-2025-06-27"],
                context_management={"edits": [edits_config]}
            )
            filtered_content = [
                block for block in response.content
                if not (hasattr(block, 'type') and block.type == 'text' and hasattr(block, 'text') and not block.text.strip())
            ]
            messages.append({"role": "assistant", "content": filtered_content})

            cleared = False
            if hasattr(response, 'context_management') and response.context_management:
                cleared = True

            print(f"  {topic[:30]:30} | tokens: {response.usage.input_tokens:6} | cleared: {cleared}")


if __name__ == "__main__":
    print("Testing Anthropic Context Editing with Server-Side Tools")
    print("="*60)
    print("\nThis test verifies that server-side tools (web_search)")
    print("are subject to the same context clearing as client-side tools.\n")

    # Run tests
    test_context_editing_with_web_search()
    test_exclude_tools()
    test_comparison()

    print("\n" + "="*60)
    print("Test complete!")
    print("="*60)
