"""Fail-closed revision checks for asynchronous Storyroom Beat builds.

No project or sound plan is mutated here; call while holding the project's
I/O lock immediately before saving the rebuilt timeline.
"""


def assert_rebuild_is_current(start_project_version, current_project_version,
                              start_plan_revision, current_plan_revision,
                              start_inputs_fingerprint, current_inputs_fingerprint):
    """Never overwrite edits or changed media discovered after a build began."""
    if (start_project_version != current_project_version
            or start_plan_revision != current_plan_revision
            or start_inputs_fingerprint != current_inputs_fingerprint):
        raise ValueError(
            'The project, sound-bite plan, or source inputs changed while the '
            'Beat storyboard was rebuilding. No timeline was saved. '
            'Your newer edits are preserved; review and rebuild the current inputs.'
        )
