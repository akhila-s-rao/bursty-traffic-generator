This is a bursty traffic generator as created by the authors of this Github repository (links to their research papers are linked in there)
https://github.com/signetlabdei/ns-3-vr-app

The idea is to send bursty traffic as generated from VR/XR devices. This traffic generator can play recorded traces from real world scenarios (described in their work). It has also created a model for these scenarios and can hence generate unlimited traces from each.

Akhila Rao has simply taken the ns3 implementaiton of this component and ported it from the C++ ns3 specific implementaiton to a python implementation (with some heavy vibe coding) 

Open and read the contents of the vr_burst_receiver.sh and vr_burst_sender.sh files to learn how to setup and run the receiver and sender. 

Do 

./vr_burst_receiver.py --help
./vr_burst_sender.py --help

to understand the input options and what they mean

You can save your desired settings in the .sh files and run 
bash vr_burst_receiver.sh at the receiver
and 
bash vr_burst_sender.sh at the sender
