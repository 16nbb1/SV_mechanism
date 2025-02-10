#!/usr/bin/env python3
import numpy as np
import pandas as pd
import math
import seaborn as sns
import matplotlib.patches as mpatches
import glob
import itertools
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
import hdbscan
import scipy.stats as stats
import statsmodels.api as sm
from statsmodels.formula.api import ols
from scipy import stats
from statsmodels.stats.multitest import multipletests
import hdbscan
from sklearn.metrics import silhouette_score, silhouette_samples
from scipy.spatial import distance_matrix
from scipy.stats import fisher_exact
import os
import datetime
from pytz import timezone
from sys import argv
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error
from math import sqrt
from sklearn.metrics import f1_score
from sklearn.metrics import classification_report
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler
import joblib

print('\n **********************')
print('START TIME:', datetime.datetime.now(timezone('EST')))

path = str(argv[1])
searching = str(argv[2])
searching2 = str(argv[3])
pcs_param = int(argv[4])
min_cluster_size_param = int(argv[5])
metric_param = str(argv[6])

project = str(argv[7])
loc = str(argv[8])
typer = str(argv[9])

print('PARAMS;')
print('PCs', pcs_param)
print('min_cluster_size', min_cluster_size_param)
print('metric', metric_param)

def top_two_probs_diff(probs):
	sorted_probs = np.sort(probs)
# calculating the difference between the sorted probabilities
	return sorted_probs[-1] - sorted_probs[-2]

all_files = glob.glob(os.path.join(path , '*'+searching))
li = []

for filename in all_files:
	df = pd.read_csv(filename, index_col=None, sep='\t')
	chromo = filename.split(searching2)[1].split('.')[0]
	svtype = filename.split(searching2)[1].split('.')[1].split('_')[0]
	df['chromo'] = chromo
	df['svtype'] = svtype

	li.append(df)
big = pd.concat(li, axis=0, ignore_index=True)

testchromo = ['chr3', 'chr5', 'chr14', 'chr17', 'chr20', 'chr22']
big_train = big[~big.chromo.isin(testchromo)]
big_train = big_train.reset_index(drop=True)


# Identifying columns which show sign. mean difference across the homology classes
pval_grab = []
cols_grab = []

for i in list(big_train.filter(like='zscore').columns):
	lol = stats.f_oneway(big_train[i][big_train['mechID_homo'] == 'NHEJ'],big_train[i][big_train['mechID_homo'] == 'SSAaEJ'],big_train[i][big_train['mechID_homo'] == 'HR'], big_train[i][big_train['mechID_homo'] == 'Undefined'], )
	pval_grab.append(lol[1])
	cols_grab.append(i)

qval_grab = np.array(multipletests(pval_grab)[1])
index_grab = np.where(qval_grab<0.05)[0]

# these are the columns that are showing up as sign from the above anova
col_want = [cols_grab[i] for i in index_grab]
print(col_want)
print(len(col_want))
col_want.append('mechID_homo')
col_want.append('chromo')
big_train_filt = big_train[col_want]


# Now we want to reduce the dimensionality by purposefully clearing out highly correlated columns
# We'll search for high-corr pairs and drop one

corr_matrix = big_train_filt.filter(like='zscore').corr().abs()

# Select upper triangle of correlation matrix
upper = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool))
to_drop = [column for column in upper.columns if any(upper[column] > 0.95)]
columns_to_keep = list(set(big_train_filt.columns) - set(to_drop))
print(columns_to_keep)
print(len(columns_to_keep))
big_train_filt_reduced = big_train_filt[columns_to_keep]
#print("Columns to drop:", to_drop)

split1_train = big_train_filt_reduced

# Now were going to perform the PCA part

x_scaled = StandardScaler().fit_transform(split1_train.filter(like='zscore'))
pca = PCA(n_components=pcs_param)
pca_features = pca.fit_transform(x_scaled)

print('Shape before PCA: ', x_scaled.shape)
print('Shape after PCA: ', pca_features.shape)

pcs_naming = []
for i in range(1,pcs_param+1):
	take = 'PCA'+str(i)
	pcs_naming.append(take)

pca_df = pd.DataFrame(data=pca_features,columns=pcs_naming)
pca_df['target'] = list(split1_train['mechID_homo'])

# Applying the hdbscan itself
split1_train_att = pd.concat([split1_train, pca_df], axis=1)
clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size_param, metric = metric_param, prediction_data=True).fit(pca_features)
soft_clusters = hdbscan.all_points_membership_vectors(clusterer)

# SAVE THIS MODEL using joblib!
joblib.dump(clusterer, '/home/nboev/projects/def-sushant/nboev/analysis/'+project+'/'+loc+'/IDmechsvSIM/20240625/splitsChromo/models/HDBSCANtraining'+typer+'.HOMO.sav')

if soft_clusters.shape[1] <1:
	print('These params do not produce suff clusters')
	sys.exit("These params do not produce suff clusters")

print('number of clusters identified', soft_clusters.shape[1])
for j in range(0, soft_clusters.shape[1]):
	split1_train_att['fuzzy'+str(j)] = list(soft_clusters[:,j])

fuzzy_columns = split1_train_att.loc[:,split1_train_att.columns.str.startswith('fuzzy')].columns
split1_train_att['fuzzy'] = split1_train_att.loc[:,fuzzy_columns].idxmax(axis=1)
split1_train_att['sumprobs'] = split1_train_att.loc[:, fuzzy_columns].sum(axis=1)

diffs = np.array([top_two_probs_diff(x) for x in soft_clusters])
split1_train_att['diffs'] = list(diffs)

# getting the most confident variants
for idx, row in split1_train_att.iterrows():
	if (row.diffs > 0.25) & (row.sumprobs > 0.5):
		split1_train_att.loc[idx, 'Forced'] = True
	else:
		split1_train_att.loc[idx, 'Forced'] = False

print(split1_train_att.groupby(['fuzzy', 'Forced']).size())

print('Calculating silhouette score')
print('including all the entries')
clusterlabel_hdbscan_fuzzy = list(split1_train_att['fuzzy'])
print(silhouette_score(pca_features, clusterlabel_hdbscan_fuzzy))

forced_index = list(split1_train_att[split1_train_att.Forced == True].index)
forced_df = split1_train_att.iloc[forced_index]
forced_pca = pca_features[forced_index]
print('including forced entries')
clusterlabel_hdbscan_fuzzy = list(forced_df['fuzzy'])
print(silhouette_score(forced_pca, clusterlabel_hdbscan_fuzzy))

# Doing cluster identifications:
# identifying dominant workflow labels across all the clusters
clusterids = []
labels = []

for j in range(0, soft_clusters.shape[1]):
	a = len(split1_train_att[(split1_train_att.Forced ==True) & (split1_train_att.fuzzy=='fuzzy'+str(j))& (split1_train_att.target == 'HR')])
	b = len(split1_train_att[(split1_train_att.Forced ==True) & (split1_train_att.fuzzy=='fuzzy'+str(j))& (split1_train_att.target == 'SSAaEJ')])
	c = len(split1_train_att[(split1_train_att.Forced ==True) & (split1_train_att.fuzzy=='fuzzy'+str(j))& (split1_train_att.target == 'NHEJ')])
	d = len(split1_train_att[(split1_train_att.Forced ==True) & (split1_train_att.fuzzy=='fuzzy'+str(j))& (split1_train_att.target == 'Undefined')])
	clusterids.append([a,b,c,d])
	labels.append('fuzzy'+str(j))
table = np.array(clusterids)
print(table)

tabledf = pd.DataFrame(table.T, columns = labels, index = ['HR', 'SSAaEJ', 'NHEJ', 'Undefined'])
tabledf_prop = (tabledf.T/tabledf.sum(axis=1)).T
print(tabledf_prop)

nhejlike = []
hrlike = []

for j in range(0, soft_clusters.shape[1]):
	if tabledf_prop.idxmax(axis=0)['fuzzy'+str(j)] == 'NHEJ':
		print('pseudo identity of fuzzy'+str(j))
		nhejlike.append('fuzzy'+str(j))
	if tabledf_prop.idxmax(axis=0)['fuzzy'+str(j)] == 'HR':
		hrlike.append('fuzzy'+str(j))


tabledf['nhej_like'] = tabledf[nhejlike].sum(axis=1)
tabledf['hr_like'] = tabledf[hrlike].sum(axis=1)

a = tabledf.loc['NHEJ', 'nhej_like']
b = tabledf.loc['HR', 'nhej_like']
c = tabledf.loc['NHEJ', 'hr_like']
d = tabledf.loc['HR', 'hr_like']

print([[a,b],[c,d]])
res = fisher_exact([[a,b],[c,d]])
print('OR' ,res[0])

# we're also going to check the number of point used within the separation:
grouped = split1_train_att.groupby(['target', 'Forced']).size().reset_index(name='count')
grouped['proportion'] = grouped.groupby('target')['count'].transform(lambda x: x / x.sum())
print(grouped)

# let's save the results which we can use to optimize knn
big_train.to_csv('/home/nboev/projects/def-sushant/nboev/analysis/'+project+'/'+loc+'/IDmechsvSIM/20240625/splitsChromo/models/results/trainingALL'+typer+'.HOMO.tsv', sep='\t', index=False)
split1_train_att.to_csv('/home/nboev/projects/def-sushant/nboev/analysis/'+project+'/'+loc+'/IDmechsvSIM/20240625/splitsChromo/models/results/trainingSHORT'+typer+'.HOMO.tsv', sep='\t', index=False)

# Now we're going to prepare for finding the optimal KNN parameters:
tocluster = split1_train_att[split1_train_att.Forced == True]

st_x= StandardScaler()
print(len(tocluster))

# the different splits were going to use..
split1 = ['chr1', 'chr8', 'chr19']
split2 = ['chr6', 'chr16', 'chrX']
split3 = ['chr2', 'chr12', 'chrY']
split4 = ['chr10', 'chr11', 'chr21']
split5 = ['chr7', 'chr13', 'chr18']
split6 = ['chr4', 'chr9', 'chr15']

splitting = [split1, split2, split3, split4, split5, split6]
scoring_avg = []
scoring_std = []
scoring_raw = []

k_values = [i for i in range (int(np.sqrt(len(tocluster)))-50,int(np.sqrt(len(tocluster)))+50,10)]
print(k_values)
for i in k_values:
	print(i)
	scoring = []
	for j in splitting:
		print(j)
		train = tocluster[tocluster['chromo'].isin(j)]
		print(len(train))
		test = tocluster[~tocluster['chromo'].isin(j)]
		print(len(test))

		pca = PCA(n_components=pcs_param)

		X_train = train.filter(like='zscore')
		X_train= st_x.fit_transform(X_train)
		X_train = pca.fit_transform(X_train)
		y_train = train.fuzzy

		X_test = test.filter(like='zscore')
		X_test= st_x.transform(X_test)
		X_test = pca.transform(X_test)

		y_test = test.fuzzy

# just use the default distance..?
		knn = KNeighborsClassifier(n_neighbors=i, metric = 'euclidean')
		knn.fit(X_train, y_train)
		y_pred = knn.predict(X_test)
		scoring.append(knn.score(X_test, y_test))
		print(knn.score(X_test, y_test))
		pca_df_test = pd.DataFrame(data=X_test, columns=['PC1', 'PC2',  'PC3', 'PC4', 'PC5',] )
		pca_df_test['preds'] = list(y_pred)
	scoring_raw.append(scoring)
	scoring_avg.append(np.mean(scoring))
	scoring_std.append(np.std(scoring))


print('raw scoring')
print(scoring_raw)
print('average scoring')
print(scoring_avg)
print('std scoring')
print(scoring_std)

# this will always be super high.. so let's use the square root
print('the k were going to use', k_values[np.argmin(scoring_std)])

ktouse = k_values[np.argmin(scoring_std)]

# doing the training on the entire dataset now...
train = tocluster
print(train.head())

X_train = train.filter(like='zscore')
X_train= st_x.fit_transform(X_train)
pca = PCA(n_components=5)
X_train = pca.fit_transform(X_train)

joblib.dump(st_x, '/home/nboev/projects/def-sushant/nboev/analysis/'+project+'/'+loc+'/IDmechsvSIM/20240625/splitsChromo/models/SCALERtraining'+typer+'.HOMO.sav')
joblib.dump(pca, '/home/nboev/projects/def-sushant/nboev/analysis/'+project+'/'+loc+'/IDmechsvSIM/20240625/splitsChromo/models/PCAtraining'+typer+'.HOMO.sav')

y_train = train.fuzzy
knn = KNeighborsClassifier(n_neighbors=ktouse, metric = 'euclidean')
knn.fit(X_train, y_train)

joblib.dump(knn, '/home/nboev/projects/def-sushant/nboev/analysis/'+project+'/'+loc+'/IDmechsvSIM/20240625/splitsChromo/models/KNNtraining'+typer+'.HOMO.sav')

print(knn.score(X_train, y_train))

colstokeep = tocluster.filter(like='zscore').columns
print(*colstokeep, sep='\n')

big_test = big[big.chromo.isin(testchromo)]
print(big_test.head())

big_test = big_test.reset_index(drop=True)
bigtestX = big_test[colstokeep]
X_test = st_x.transform(bigtestX)
X_test = pca.transform(X_test)

y_pred = knn.predict(X_test)
big_test['fuzzypred'] = y_pred

print(big_test.groupby('fuzzypred').size())






