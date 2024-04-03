#!/bin/env python3

# ------------------------------------------------------------------------------------------
# Program: Plot Data
#
# Filename: plotData.py
#
# Author: Garth Watney
#
# ------------------------------------------------------------------------------------------

import json
import os
import argparse
from typing import List, Optional
from pydantic import BaseModel
from typing import List
import matplotlib.pyplot as plt
from json2table import convert


css_style = """
<style>
    table {
        width: 100%;
        border-collapse: collapse;
    }
    th, td {
        border: 1px solid black;
        padding: 8px;
        text-align: left;
    }
</style>
"""

# -------------------------------------------------------------------------------------
# These Pydantic classes define the JSON Data
#
# -------------------------------------------------------------------------------------

# Define your Pydantic models
class TimeTag(BaseModel):
    seconds: int
    useconds: int
    timeBase: int
    context: int

class PairHistory(BaseModel):
    time: float
    value: float

class Data(BaseModel):
    type: str
    history: List[float]
    pairHistory: List[PairHistory]

class Packet(BaseModel):
    PacketDescriptor: Optional[int]
    Id: Optional[int]
    Priority: Optional[int]
    TimeTag: Optional[TimeTag]
    ProcTypes: Optional[int]
    UserData: Optional[List[int]]
    DpState: Optional[int]
    DataSize: Optional[int]
    headerHash: Optional[int]
    dataHash: Optional[int]

class DataItem(BaseModel):
    dataId: int
    data: Data


# ------------------------------------------------------------------------------------------
# main program
#
# ------------------------------------------------------------------------------------------

# Application arguments
parser = argparse.ArgumentParser(description='Make a table and plot of the JSON Data.')
parser.add_argument('json', help='The input json file')
args = parser.parse_args()


with open(args.json, 'r') as file:
    json_data = json.load(file)


# Create a Table
#
baseName = os.path.basename(args.json)
htmlFile = os.path.splitext(baseName)[0] + '.html'
pngFile = os.path.splitext(baseName)[0] + '.png'


# Check if the json_content is a list
with open(htmlFile, 'w') as html_file:
    html_file.write(css_style)
    if isinstance(json_data, list):
        # Iterate over each dictionary in the list and convert it to an HTML table
        for item in json_data:
            # Ensure that each item is a dictionary before converting
            if isinstance(item, dict):
                html = convert(item)
                html_file.write(html + "<br>")  # Add a line break between tables
            else:
                print("Item is not a dictionary. Cannot convert to table.")
    else:
        # If json_content is a dictionary, convert it directly
        html = convert(json_data)
        html_file.write(html + "<br>")  # Add a line break between tables


# Create a Plot
#
packets = []
for item in json_data:
    if 'PacketDescriptor' in item:
        continue
    elif 'dataId' in item:
        packets.append(DataItem(**item))


sineData = []
for packet in packets:
    data = packet.data.pairHistory[0]
    sineData.append((data.time, data.value))


# Unzip the data into two lists, times and values
times, values = zip(*sineData)

# Create the plot
plt.figure(figsize=(10, 6))  # You can adjust the figure size as needed
plt.plot(times, values, label='SignalGen Data', marker='o')  # 'o' creates a circle marker at each data point

# Adding labels and title
plt.xlabel('Time')
plt.ylabel('Value')
plt.title('SG1.SignalGen')
plt.legend()

# Display the plot
plt.grid(True)
plt.savefig(pngFile, dpi=300)

