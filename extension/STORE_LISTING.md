# Chrome Web Store listing

Everything to paste into the Chrome Web Store developer dashboard, tab by tab.

## Store listing tab

**Summary** (from the manifest, 105 of 132 characters)

Dims videos the moment seizure-risk flashing starts, and checks a video for flashing before you watch it.

**Description**

```
FlashGuard protects you from flashing in videos that can trigger photosensitive seizures.

I have epilepsy, and most videos are never checked for this. FlashGuard checks every frame of the video you're watching against the WCAG accessibility rules for flashing (more than 3 flashes in any one second fails).

LIVE PROTECTION
When flashing goes over the limit, FlashGuard dims the video almost to black (or pauses it, if you prefer) and shows a short notice. When the flashing stops, the picture comes back on its own.

CHECK A VIDEO BEFORE YOU WATCH IT
Click the FlashGuard icon and choose "Check this video first." FlashGuard plays the video hidden and muted, finds every flashing section, and lists them. While you watch, those sections are dimmed or skipped automatically.

SETTINGS
• Dim or pause when flashing starts
• Dim or skip sections found by a check
• React at the WCAG limit, or an extra sensitive setting

PRIVATE BY DESIGN
Everything runs on your own computer. FlashGuard never sends your data anywhere, and has no ads, tracking or analytics.

GOOD TO KNOW
• Live protection needs a fraction of a second of flashing to recognize it. Use "Check this video first" to be warned ahead of time.
• Streaming services with copy protection (like Netflix or Disney+) don't let extensions read their video, so FlashGuard can't check those.
• Pattern flicker like flipping stripes or checkerboards isn't detected yet.

FlashGuard is a screening tool based on the WCAG flash limits, not a medical device. It can't catch everything, so it doesn't replace other precautions.

Open source: github.com/npnair/flashguard
```

**Category:** Accessibility

**Language:** English

**Store icon:** `icons/icon128.png`

**Screenshots:** `store-assets/screenshot1.png`, `store-assets/screenshot2.png` (1280 x 800)

**Small promo tile:** `store-assets/promo_tile_440x280.png`

**Homepage URL:** https://github.com/npnair/flashguard

**Support URL:** https://github.com/npnair/flashguard/issues

## Privacy tab

**Single purpose**

```
FlashGuard protects people with photosensitive epilepsy by detecting flashing in videos that exceeds the WCAG flash limits, then dimming, pausing or skipping that part of the video.
```

**Permission justification: storage**

```
Saves the user's settings (on/off, how to react, sensitivity) and the results of "Check this video first," so a checked video stays protected when the user returns to it. Nothing is sent off the device.
```

**Permission justification: host permission** (the content script runs on all URLs)

```
Flashing can appear in a video on any website, so the content script must run on every page to find video players, read their frames and dim the video when dangerous flashing starts. It only reads video frames, processes them locally, and never sends any page data anywhere.
```

**Are you using remote code?** No, I am not using remote code.

**Data usage:** check none of the data types. FlashGuard reads video frames but processes them on the device and never collects or transmits them. Then check all three certifications:

- I do not sell or transfer user data to third parties, outside of the approved use cases
- I do not use or transfer user data for purposes that are unrelated to my item's single purpose
- I do not use or transfer user data to determine creditworthiness or for lending purposes

**Privacy policy URL:** https://npnair.github.io/flashguard/privacy.html

## Distribution tab

**Payments:** Free

**Visibility:** Public

**Regions:** All regions

## Test instructions (if asked)

```
No account or login is needed. Open any video (for example on YouTube), click the FlashGuard icon and choose "Check this video first" to see a check run. Live protection runs automatically on every video.
```
