# Official ParseHub migration status

The shipping application still uses the accepted patched parser/runtime combination. The original-package path is experimental and is not the default installed engine.

## Implemented and validated

- Original ParseHub 2.4.0 wheel loading without changing its package source.
- Dynamic discovery of 24 parsers and conversion to application preview contracts.
- Self-contained embedded Python layout and relocation smoke checks.
- Isolated candidate selection, inventory verification, launch preflight and rollback policy.
- Development-signature admission: authenticated inventory, original-wheel byte comparison, replay and upstream downgrade rejection.
- Integration with the real task service, commit authorization and per-post archive workflow.
- Public video samples from Douyin, Kuaishou and Bilibili completed; a Xiaohongshu gallery completed with 15 images and 13 paired Live Photo videos. User-provided sample links, download outputs and credentials are not part of this repository.
- Weixin Channels reports an explicit local credential requirement. Authenticated Channels downloading has not passed this validation.

Actual downloaded Bilibili resolution may differ from upstream source-post dimensions. The experimental adapter hides unverified progressive-stream dimensions until file probing. Live Photo capability is inferred from the current parsed result.

## Not production-ready yet

Candidate admission currently covers locally assembled environments, not a complete online installer. Production Python selection, full dependency artifact locking, remote artifact installation and native settings integration are pending. The embedded Python used in the layout proof is not the selected production baseline.

Initial/media URL checks do not confine every internal upstream HTTP client. Only the explicitly allowed experimental platforms enter the task adapter; discovering a parser does not mean that all platforms have passed task integration. Download confirmation currently reparses the source to refresh media URLs.

Development signing keys are ephemeral and are not production trust roots. No private key, Cookie, local runtime or QA database is published. Existing installed clients continue using the signed stable component channel.
