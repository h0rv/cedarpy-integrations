---
title: When to write Python and when to write Cedar
---

**Choose the authoring language per policy, not per route.** A detail view and a background worker can import the same document policy. An export route can use a different policy written in a `.cedar` file. Neither needs a copy of the other's rules.

## When Python earns its place

Suppose an application already defines `DocumentState.SEALED`. A reviewer who knows the model can read `forbid_when=document.state == DocumentState.SEALED` without learning another name for the same state. An editor can find references to the member, and a type checker can catch a misspelled member before the service starts. [Shared Python policies](../policies/) shows the complete example.

That advantage is narrower than “Python is typed and Cedar isn't.” [Cedar validates policies against a schema](https://docs.cedarpolicy.com/policies/validation.html), including field names and action types. What the Python checker knows here that a Cedar `String` field doesn't is *which Python enum* the application uses. The example explicitly binds the field to that enum. Neither checker can tell you whether making a sealed document public was the right business decision.

## When a Cedar file is simpler

| If you need… | Prefer… |
| --- | --- |
| A policy local to a Python application, using ownership, enum values, or boolean session facts | Typed Python if it makes the rule easier to review |
| The same policy across Python and another language, or policy changes deployed separately from application code | A `.cedar` file and a shared schema |
| Group ancestry, set operations, optional attributes guarded by `has`, or other expressions beyond the Python helpers | Native Cedar rather than a Python workaround |
| Policy supplied by a customer or an administrator | Cedar text parsed as data. Never import untrusted Python to load a policy. |

Both forms are policy as code. They differ in what it takes to see the effective policy. A reviewer can read a Cedar file directly. A Python module executes on import. If it branches on an environment variable or performs a network lookup, two workers could build different policies from the same commit. Keep shared policy modules deterministic. Supply changing facts at request time instead.

## Where equivalence stops

The Python helpers build Cedar syntax nodes. They do not decide whether a request is allowed. [Cedar combines permits and forbids](https://docs.cedarpolicy.com/auth/authorization.html): a matching forbid wins; without a matching permit the answer is deny. Review the emitted Cedar alongside the Python when a rule changes. For static policies you can inspect it with `print(documents.read)` without maintaining a second policy file.

The integrations accept static policy sets. They reject templates and linked sets at startup rather than validating a text rendering that could lose a link. If you rely on template linking, keep the linked set with the native evaluator.

Separate *what Cedar can express* from *what an adapter can enforce*. Writing a valid Cedar file does not make an arbitrary join or count safe. The SQL reader handles flat row projections, checks each candidate with Cedar, and rejects a relevant forbid it cannot translate. Use the native evaluator with the required facts for decisions outside that boundary. Also check diagnostics: Cedar can skip an errored policy, whereas the integrations refuse to return a successful check with evaluation errors.

## A practical stopping rule

Try the Python form on a few real policies. Compare the generated decisions to reviewed Cedar on allowed, denied, and missing-fact requests. Keep a case where a permit and a forbid both match. Verify changes to the domain schema regenerate the checked-in references. Give a reviewer the Python and emitted Cedar and ask *who gains access in this change?*

If answering that question requires tracing helper classes, or a policy needs features outside the supported subset, keep that policy in Cedar. The goal is one readable definition per rule, not a Python spelling for the whole language.
