# B7 S1 recording shot list

Generated from the successful local S1 run in timeline.json. Captions come from observed UI actions or core events.

## Recordings

| File | Resolution | Duration |
|---|---:|---:|
| demo-s1-desktop-paced-source.webm | 1920 x 1080 | 175.52 s |
| demo-s1-phone-paced-source.webm | 390 x 844 | 176.44 s |
| demo-s1-desktop-full.mp4 | 1920 x 1080 | 150.00 s |
| demo-s1-phone-full.mp4 | 390 x 844 | 150.00 s |
| demo-s1-desktop-60s.mp4 | 1920 x 1080 | 60.00 s |
| demo-s1-phone-60s.mp4 | 390 x 844 | 60.00 s |

The full cuts use 1.17x desktop and 1.18x phone playback. The 60-second cuts use excerpted shots. Both compressed formats carry an on-screen label.

## Observed shots

| Time | Event | Caption source |
|---:|---|---|
| 8.62 s | LocalMockSignIn | A new operator signs in through the local mock. |
| 32.41 s | WorkspaceCreated | The operator's simulated practice site is ready. |
| 43.03 s | InvitationAccepted | A separate account joins with the approver role. |
| 59.13 s | QuestionAsked #7 | Question 1: On your phone, open the list of available networks. Is this site's network missing, still connecting, or connected? |
| 68.72 s | ObservationRecorded #10 | Facilities technician (simulated) answered from the simulated site card: connected. |
| 69.57 s | QuestionAsked #8 | Question 2: Please go to equipment room 1. When you get there: Look at the internet router. Is the light marked INTERNET green, red, or off? |
| 76.33 s | ObservationRecorded #13 | Network technician (simulated) answered from the simulated site card: green. |
| 77.27 s | QuestionAsked #9 | Question 3: On your phone, does a normal website open? Please say yes or no. |
| 83.03 s | ObservationRecorded #16 | Site staff (simulated) answered from the simulated site card: yes. |
| 83.89 s | QuestionAsked #12 | Question 4: On your phone, does a normal website open? Please say yes or no. |
| 89.57 s | ObservationRecorded #21 | Facilities technician (simulated) answered from the simulated site card: yes. |
| 90.42 s | QuestionAsked #15 | Question 5: Look at the internet connection box. Is its status light green, red, or off? |
| 96.09 s | ObservationRecorded #26 | Network technician (simulated) answered from the simulated site card: green. |
| 97.03 s | QuestionAsked #20 | Question 6: Please go to equipment room 2. When you get there: Look at the box with several network cables. Are its small lights green, orange, or off? |
| 103.94 s | ObservationRecorded #29 | Site staff (simulated) answered from the simulated site card: off. |
| 104.97 s | QuestionAsked #25 | Question 7: Please go to the second-floor corridor. When you get there: Please look at the corridor nearby. Are its lights on or off? |
| 111.16 s | ObservationRecorded #32 | Facilities technician (simulated) answered from the simulated site card: on. |
| 112.16 s | QuestionAsked #28 | Question 8: Please go to the second-floor corridor. When you get there: Look at the small device on the ceiling. Is its light on or off? |
| 118.57 s | ObservationRecorded #35 | Network technician (simulated) answered from the simulated site card: off. |
| 119.44 s | QuestionAsked #31 | Question 9: Look at the small screen used to view security cameras. Is it on or off? |
| 124.55 s | ObservationRecorded #38 | Site staff (simulated) answered from the simulated site card: off. |
| 125.47 s | QuestionAsked #34 | Question 10: Please go to equipment room 2. When you get there: Look at the small screen used to view security cameras. Is it on or off? |
| 131.62 s | ObservationRecorded #40 | Facilities technician (simulated) answered from the simulated site card: off. |
| 132.54 s | DecisionReached #44 | The investigation reached DISPATCH_ELECTRICIAN_DB_C2. |
| 141.48 s | ApprovalRequested #45 | Approval requested for Reset a tripped breaker on CB_C2_7. |
| 145.81 s | ApprovalDecided #46 | The separate approver approved the repair. |
| 154.97 s | InterventionReported #48 | The approved participant reported the simulated repair. |
| 156.30 s | QuestionAsked #51 | Verification question: On your phone, open the list of available networks. Is this site's network missing, still connecting, or connected? |
| 159.77 s | VerificationResult #55 | The investigation status is verified. |
| 169.99 s | GroundTruthRevealed #56 | Reveal: CB_C2_7 tripped; commitment verified: true. |
| 173.99 s | ReplayChecked | Replay identical across 56 events. |

The emulator returns silent WAV/PCM data and the browser recording has no real participant audio. The synthetic-audio disclosure remains visible throughout the paced sources and compressed cuts.
