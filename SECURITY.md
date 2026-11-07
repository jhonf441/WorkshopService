# Security policy

## Reporting a vulnerability

Please do NOT open a public issue with details of a vulnerability. Use the **Security** tab of this repository ("Report a vulnerability", a private
advisory) or contact the maintainer through his GitHub profile. A report that says what you saw, which version (WorkshopService 2.30.5) and how to repeat it is
enough; there is no need for an exploit.

## What this plugin can do to your machine

Read [README.md](README.md) (section "Permissions and what it changes") before installing. The permissions DSF asks for, the files written on the SD
card and the Pi, the ports it opens and the safety measures are described there and in the security document of the Workshop plugins. Without users
created on the Workshop Service, the network can only look at these services (the camera relay, Vision and the G-code bridge refuse anything that changes
something) while anyone who reaches DWC is an administrator: create the administrator first.

The Workshop users and roles do not protect DWC itself: anyone who can open DWC on your network can send G-code, move the machine and edit
`config.g`, whatever the Workshop roles say (Duet has no roles of its own). Set a DWC password (`M551`) and keep the machine on a network you trust.

Nothing is sent outside your network by default. The only feature that sends data to a third party (phone notifications through ntfy.sh, optionally with
camera photos) is off until you turn it on and confirm it; the README says exactly what it sends.

## Supported versions

Only the latest release of each plugin receives fixes.
