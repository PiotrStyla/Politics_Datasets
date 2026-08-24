# RCL legal review note

## Purpose

This note gives legal reviewers a clearer starting point for RCL/RPL source
documents in the pilot. It is not a legal conclusion and does not assign an
open-content license to any document.

## Working premise

The RCL pilot downloaded documents from public URLs in the official Rządowy
Proces Legislacyjny service (`legislacja.gov.pl`). The working premise for
review is that these are public-sector legislative-process documents made
available by a public authority for transparency and possible reuse review, not
private or access-controlled files.

This premise supports collection and metadata review, but it does not by itself
make the documents training-ready. Each document still needs review for:

- public-sector information reuse status,
- attribution/source and timestamp requirements,
- possible copyright or database-right conditions,
- personal data and signature handling,
- whether redistribution of extracted text is allowed,
- whether use in a pretraining corpus is allowed or needs extra conditions.

## Sources for legal review

- RCL BIP page on reuse: RCL states that government draft acts and related
  documents are made available on the RCL subject page in the Rządowy Proces
  Legislacyjny service, and lists reuse conditions such as source/time
  attribution and information about processing.
  https://bip.rcl.gov.pl/rcl/ponowne-wykorzystywanie/3122%2CPonowne-wykorzystywanie.html
- KPRM page on public-sector information reuse: describes the right to reuse
  public-sector information and points to the current open-data/public-sector
  information reuse regime.
  https://www.gov.pl/web/premier/ponowne-wykorzystywanie
- Current statutory reference: Ustawa z dnia 11 sierpnia 2021 r. o otwartych
  danych i ponownym wykorzystywaniu informacji sektora publicznego.
  https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20210001641

## Annotation language

Use `legal_status=review_needed` until legal review confirms a release path.
Use the following `legal_basis` language for RCL pilot rows:

> Working premise: public RCL/RPL source document from the official Rządowy
> Proces Legislacyjny service. RCL BIP identifies government draft acts and
> related documents as published in RPL; public-sector information reuse should
> be reviewed under the current open-data/public-sector information reuse
> regime. No blanket dataset license assigned; verify attribution, reuse,
> copyright/database-right and PII constraints before text release or training
> use.

## Boundary

`review_needed` means "not yet cleared", not "blocked". The document is in the
legal review queue because it is public and plausibly reusable under a
public-sector information framework, but no release/training claim should be
made until the legal evidence is completed.
