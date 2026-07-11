# -*- coding: utf-8 -*-
"""
Created on Fri Jun 12 14:20:41 2026

@author: michi
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import norm
import plotly.express as px
import seaborn as sns

sns.set_theme()

DATA_PATH = "golf_shots.csv"

data = pd.read_csv(DATA_PATH)

# fig = px.bar(
#     data,
#     x = "club",
#     y = None
#     )


data = data.loc[(data["club"] == "9 Iron") & (data["distance_m"]>40)]
mu, std = norm.fit(data["distance_m"])

plt.hist(data["distance_m"], bins=10, density=True)

xmin, xmax = plt.xlim()
x = np.linspace(xmin, xmax, num=100)
p = norm.pdf(x, loc=mu, scale=std)


plt.plot(x, p)

plt.show()