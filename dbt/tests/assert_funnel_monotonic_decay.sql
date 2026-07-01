/*
    Invariant: the funnel must be monotonically decreasing per channel.
    No channel should ever have more users at step N+1 than at step N -
    that would indicate a bug in the step-detection logic of
    int_funnel__steps (e.g. a session tagged as checkout without a prior
    PDP view).

    Violations point to either a data-quality issue upstream or a logic
    bug in the intermediate model; both are P0 for an attribution deck.
*/

SELECT
    channel_key,
    users_visited,
    users_pdp,
    users_add_to_cart,
    users_checkout,
    users_purchased
FROM {{ ref('fct_funnel_steps') }}
WHERE users_pdp        > users_visited
   OR users_add_to_cart > users_pdp
   OR users_checkout    > users_add_to_cart
   OR users_purchased   > users_checkout
