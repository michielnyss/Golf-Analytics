# -*- coding: utf-8 -*-
"""
Created on Mon Jun 22 20:42:11 2026

@author: michi
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import norm
import plotly.express as px
import seaborn as sns

DATA_PATH = "golf_shots.csv"

data = pd.read_csv(DATA_PATH)

def fit_markov(data, from_col, to_col, state_order=None):
    
    n_ij = pd.crosstab(data["lie"], data["to_lie"])
    n_ij = n_ij.reindex(index=states, columns=states, fill_value=0)
    
    if state_order:
        assert list(n_ij.columns) == state_order, f"Make sure you include all states in 'state_order'"
    
    n_i = n_ij.sum(axis=1)
    
    P_ij = n_ij.div(n_i, axis=0)
    
    return P_ij

data.loc[data["stroke_type"]=="Penalty", ["lie", "to_lie"]] = "penalty"
data.loc[(data["to_lie"]=="0") | (data["to_lie"]=="unknown"), "to_lie"] = "penalty"
states = ['tee', 'fairway', 'rough', 'bunker', 'penalty', 'green']

P_ij = fit_markov(data, "lie", "to_lie", states)
    
    
data["from_dist_to_pin"] = data["dist_to_pin"]
data["to_dist_to_pin"] = data["from_dist_to_pin"] - data["distance_m"]
data["id"] = data["id"] = (
    data["round_date"].astype(str) + "/"
    + data["hole"].astype(str))
data["last_shot"] = 1
data["hole_lng"] = 1
data["hole_lat"] = 1

bins = [-np.inf ,0.01, 10, 15, 25, 50, 100, 200, 350, 500, np.inf]

labels = [
    "0",
    "<10m",
    "[10, 15)",
    "[15, 25)",
    "[25, 50)",
    "[50, 100)",
    "[100, 200)",
    "[200, 350)",
    "[350, 500)",
    ">500m"
]
state_order = labels[::-1]

data["from_dist_cat"] = pd.cut(
    data["from_dist_to_pin"],
    bins=bins,
    labels=labels,
    right=False
)

data["to_dist_cat"] = pd.cut(
    data["to_dist_to_pin"],
    bins=bins,
    labels=labels,
    right=False
)



    
    
    
    