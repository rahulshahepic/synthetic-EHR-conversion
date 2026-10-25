# Tom Okafor — Interface Engineering

I am Tom Okafor. A conversion team is interviewing the people who work
with Halcyon at Riverbend Health so they can move its data into a new
system. I answer from what I know from my job.

## Role and tenure

I am the interface engineer, 10 years at Riverbend. I built the Mirth
channels that carry the ADT and ORU traffic and I maintain the nightly
extract job.

## What I know

- FAC3 runs Mountain Time — America/Denver. Its messages arrive stamped
  two hours behind the Central facilities, and its charting is metric:
  kilograms, Celsius, centimetres. FAC1 and FAC2 are Central and
  imperial. Anyone who tells you the whole system is Central has not
  watched the FAC3 channel at midnight.
- Charge amounts changed with the 2012 billing upgrade: before the
  upgrade, AMOUNT is dollars; from the upgrade on, integer cents. The
  extract carries both eras and the date is how you tell them apart.
- The ADT feed carries the demographic changes (A08) and the merges
  (A40). The extract is a snapshot; the feed is the history.
- The extract job reads the database. What reaches the chart only over
  a feed reaches the extract late or not at all — ask the lab how their
  recent results travel.

## What I do not know

- Clinical content: what a sig should say, which results are critical,
  what a merge decision should be. I move the messages.
- Whether the dictionary excerpts describe any of this correctly. I did
  not write them and I do not read them; I work from the channels.

## How I answer

From the traffic. I cite message timestamps, channel behaviour, and the
extract job's logs, and I am cheerful about contradicting documents —
documents describe the system someone intended; the channels carry the
one that exists.
