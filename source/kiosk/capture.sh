#!/bin/bash
echo "Starting the capture of port 23..."
echo "Run your live job now."
echo "When you are done, press Ctrl+C here to stop and see the result."
echo ""

sudo rm -f /tmp/live_job.pcap
sudo tcpdump -i any port 23 -w /tmp/live_job.pcap

echo ""
echo "Capture finished. Showing the result..."
sudo tcpdump -r /tmp/live_job.pcap -A | grep -v "Bed comp" | less
