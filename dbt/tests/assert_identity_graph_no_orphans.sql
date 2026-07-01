/*
    Invariant: every raw identifier ingested into the identity graph must
    be assigned to a non-null unified_user_id after label propagation.

    An orphan would mean the graph builder silently dropped a user, breaking
    the one-row-per-unified-user guarantee that the whole composable CDP
    relies on.
*/

SELECT
    raw_id,
    unified_user_id
FROM {{ ref('int_identity__graph') }}
WHERE unified_user_id IS NULL
   OR raw_id IS NULL
