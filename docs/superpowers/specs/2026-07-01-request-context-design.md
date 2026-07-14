# Request Context Design

## Scope

Add request-scoped thread identity and session-directory accessors without introducing an API framework or wiring a request entry point that does not yet exist.

## Structure

- `app/api/__init__.py` marks the API package.
- `app/api/context.py` defines two typed `ContextVar` values with `None` defaults.
- `set_thread_context(thread_id, session_dir)` sets both values for the current context.
- `get_thread_id()` and `get_session_dir()` return the current values.

## Behavior

Before initialization, both getters return `None`. After `set_thread_context`, they return the supplied values. Python context propagation provides isolation between independently created asynchronous tasks.

## Testing

Tests verify defaults, setting and reading both values, and isolation across asynchronous task contexts. Existing tests must remain green.
