#!/usr/bin/env python
import SPyFFI.Observation
ncp = SPyFFI.Observation.SkyFFI(ra=270.0, dec=66.56070833333332)
ncp.create(todo={2:3,120:3,1800:100}, label='sparse')
