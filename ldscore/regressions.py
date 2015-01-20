'''
(c) 2014 Brendan Bulik-Sullivan and Hilary Finucane

This module contains basic functions for estimating 
	1. heritability / partitioned heritability
	2. genetic covariance
	3. genetic correlation
	4. block jackknife standard errors (hence the module name) for all of the above.
	
Numpy does this annoying thing where it treats an array of shape (M, ) very differently
from an array of shape (M, 1). In order to deal with univariate LD Score regression
and partitioned LD Score regression with the same code, everything in this module deals
with numpy matrices. 

Weird bugs may result if you pass numpy arrays or pandas dataframes without first 
converting to a matrix with the correct shape.

Terminology note -- the intended use case for this module is an LD Score regression with
n_snps SNPs included in the regression and n_annot (partitioned) LD Scores (which means 
that the number of parameters estimated in the regression will be n_annot + 1, since we
also estimate an intercept term).

'''

from __future__ import division
import numpy as np
from scipy.stats import norm
from scipy.stats import chi2
#import statsmodels.api as sm
from scipy.optimize import nnls


def kill_brackets(x):
	'''Get rid of annoying brackets in numpy arrayss'''
	x = x.replace('[[  ','')
	x = x.replace('  ]]','')
	x = x.replace('[[ ','')
	x = x.replace(' ]]','')
	x = x.replace('[[','')
	x = x.replace(']]','')
	x = x.replace('[  ','')
	x = x.replace('  ]','')
	x = x.replace('[ ','')
	x = x.replace(' ]','')
	x = x.replace('[','')
	x = x.replace(']','')
	return(x)

def _weight(x, w):
	
	'''
	Re-weights x by multiplying by w.
	
	Parameters
	----------
	x : np.matrix with shape (n_row, n_col)
		Rows are observations.
	w : np.matrix with shape (n_row, 1)
		Regression weights.

	Returns
	-------
	
	x_new : np.matrix with shape (n_row, n_col)
		x_new[i,j] = x[i,j] * w[i]
	
	'''
	if np.any(w <= 0):
		raise ValueError('Weights must be > 0')

	w = np.sqrt(w/ float(np.sum(w)))
	x_new = np.multiply(x, w)
	return x_new
	

def _append_intercept(x):

	'''
	Appends an intercept term to the design matrix for a linear regression.
	
	Parameters
	----------
	x : np.matrix with shape (n_row, n_col)
		Design matrix. Columns are predictors; rows are observations. 

	Returns
	-------
	
	x_new : np.matrix with shape (n_row, n_col+1)
		Design matrix with intercept term appended.
	
	'''
	
	n_row = x.shape[0]
	int = np.matrix(np.ones(n_row)).reshape((n_row,1))
	x_new = np.concatenate((x, int), axis=1)
	return x_new

def _gencov_weights(ld, w_ld, N1, N2, No, M, h1, h2, rho_g, rho):

	'''
	Computes appropriate regression weights to correct for heteroskedasticity in the 
	bivariate LDScore regression under and infinitesimal model. These regression weights are 
	approximately equal to the reciprocal of the conditional variance function
	1 / var(betahat1*betahat2 | LD Score)
	
	Parameters
	----------
	ld : np.matrix with shape (n_snp, 1) 
		LD Scores (non-partitioned)
	w_ld : np.matrix with shape (n_snp, 1)
		LD Scores (non-partitioned) computed with sum r^2 taken over only those SNPs included 
		in the regression.
	M : int > 0
		Number of SNPs used for estimating LD Score (need not equal number of SNPs included in
		the regression).
	N1, N2 :  np.matrix of ints > 0 with shape (n_snp, 1)
		Number of individuals sampled for each SNP for each study.
	No : int
		Number of overlapping individuals.
	h1, h2 : float in [0,1]
		Heritability estimates for each study.
	rhog : float in [0,1]
		Genetic covariance estimate.
	rho : float in [0,1]
		Phenotypic correlation estimate.
	
	Returns
	-------
	w : np.matrix with shape (n_snp, 1)
		Regression weights. Approx equal to reciprocal of conditional variance function.
	
	'''

	h1 = max(h1,0) 
	h2=max(h2,0)
	h1 = min(h1,1)
	h2=min(h2,1)
	rho_g = min(rho_g,1)
	rho_g = max(rho_g, -1)	
	ld = np.fmax(ld, 1.0)
	w_ld = np.fmax(w_ld, 1.0) 
	# prevent integer division bugs with np.divide
	N1 = N1.astype(float); N2 = N2.astype(float); No = float(No)
	a = h1*ld / M + np.divide(1.0, N1)
	b = h2*ld / M + np.divide(1.0, N2)
	c = rho_g*ld / M + np.divide(No*rho, np.multiply(N1,N2))
	het_w = np.divide(1.0, np.multiply(a, b) + 2*np.square(c))
	oc_w = np.divide(1.0, w_ld)
	# the factor of 3 is for debugging -- for degenerate rg (same sumstats twice)
	# the 3 makes the h2 weights equal to the gencov weights
	w = 3*np.multiply(het_w, oc_w)
	return w

def _hsq_weights(ld, w_ld, N, M, hsq):

	'''
	Computes appropriate regression weights to correct for heteroskedasticity in the LD 
	Score regression under an infinitesimal model. These regression weights are 
	approximately equal to the reciprocal of the conditional variance function
	1 / var(chi^2 | LD Score)
	
	Parameters
	----------
	ld : np.matrix with shape (n_snp, 1) 
		LD Scores (non-partitioned). 
	w_ld : np.matrix with shape (n_snp, 1)
		LD Scores (non-partitioned) computed with sum r^2 taken over only those SNPs included 
		in the regression.
	N :  np.matrix of ints > 0 with shape (n_snp, 1)
		Number of individuals sampled for each SNP.
	M : int > 0
		Number of SNPs used for estimating LD Score (need not equal number of SNPs included in
		the regression).
	hsq : float in [0,1]
		Heritability estimate.
	
	Returns
	-------
	w : np.matrix with shape (n_snp, 1)
		Regression weights. Approx equal to reciprocal of conditional variance function.
	
	'''
	hsq = max(hsq,0); hsq = min(hsq,1)
	ld = np.fmax(ld, 1.0)
	w_ld = np.fmax(w_ld, 1.0) 
	c = hsq * N / M
	het_w = np.divide(1.0, np.square(1.0+np.multiply(c, ld)))
	oc_w = np.divide(1.0, w_ld)
	w = np.multiply(het_w, oc_w)
	return w


def obs_to_liab(h2_obs, P, K):
	'''
	Converts heritability on the observed scale in an ascertained sample to heritability 
	on the liability scale in the population.

	Parameters
	----------
	h2_obs : float	
		Heritability on the observed scale in an ascertained sample.
	P : float in [0,1]
		Prevalence of the phenotype in the sample.
	K : float in [0,1]
		Prevalence of the phenotype in the population.
		
	Returns
	-------
	h2_liab : float
		Heritability of liability in the population.
		
	'''
	if K <= 0 or K >= 1:
		raise ValueError('K must be in the range (0,1)')
	if P <= 0 or P >= 1:
		raise ValueError('P must be in the range (0,1)')
	
	thresh = norm.isf(K)
	conversion_factor = K**2 * (1-K)**2 / (P * (1-P) * norm.pdf(thresh) **2)
	return h2_obs * conversion_factor
	

class Hsq(object):
	'''
	The conflict between python and genetics capitalization conventions (capitalize 
	objects, but additive heritability is lowercase) `akes me sad :-(
	
	Class for estimating heritability / partitioned heritability from summary statistics.
	
	Parameters
	----------
	chisq : np.matrix with shape (n_snp, 1)
		Chi-square statistics. 
	ld : np.matrix with shape (n_snp, n_annot) 
		LD Scores.	
	w_ld : np.matrix with shape (n_snp, 1)
		LD Scores (non-partitioned) computed with sum r^2 taken over only those SNPs included 
		in the regression.
	N :  np.matrix of ints > 0 with shape (n_snp, 1)
		Number of individuals sampled for each SNP.
	M : np.matrix of ints with shape (1, n_annot) > 0
		Number of SNPs used for estimating LD Score (need not equal number of SNPs included in
		the regression).
	num_blocks : int, default = 1000
		Number of block jackknife blocks.
	intercept : none or float
		If none, fits LD Score regression w/ intercept. If float, constrains the intercept
		to equal the given float.
	
	Attributes
	----------
	N : int
		Sample size. In a case/control study, this should be total sample size: number of 
		cases + number of controls. NOT some measure of effective sample size that accounts 
		for case/control ratio. The case-control ratio comes into play when converting from
		observed to liability scale (in the function obs_to_liab).
	M : np.matrix of ints with shape (1, n_annot)
		Total number of SNPs per category in the reference panel used for estimating LD Score.
	M_tot : int
		Total number of SNPs in the reference panel used for estimating LD Score.
	n_annot : int
		Number of partitions.
	n_snp : int
		Number of SNPs included in the regression.	
	mean_chisq : float
		Mean chi-square.
	w_mean_chisq : float
		Weighted mean chi-square (with the same weights as the regression).
	lambda_gc : float
		Devlin and Roeder lambda GC (median chi-square / 0.4549).
	hsq_cov : np.matrix with shape (n_annot, n_annot)
		Block jackknife estimate of variance-covariance matrix of partitioned h2 estimates.
	cat_hsq : np.matrix with shape (1, n_annot)
	 	Partitioned heritability estimates.
	cat_hsq_se : np.matrix with shape (1, n_annot)
		Standard errors of partitioned heritability estimates.
	intercept : float
		LD Score regression intercept.
	intercept_se : float
		Standard error of LD Score regression intercept.
	tot_hsq : float
		Total h2g estimate.
	tot_hsq_se : float
		Block jackknife estimate of standard error of the total h2g estimate. 
	prop_hsq : np.matrix with shape (1, n_annot)
		Proportion of h2 per annotation.
	M_prop : np.matrix with shape (1, n_annot)
		Proportion of SNPs (in reference panel) per annotation. 
	enrichment : np.matrix with shape (1, n_annot)
		Per category enrichment of h2 relative to all SNPs. Precisely, 
		(h2 per SNP in category) / (h2 per SNP overall).
	_jknife : LstsqJackknife
		Jackknife object.
		
	Methods
	-------
	_aggregate(y, x, M_tot):
		Aggregate estimator. 
	summary(ref_ld_colnames):
		Returns a summary of the LD Score regression.
	summary_intercept():
		Returns a summary of the LD Score regression focused on the intercept.
		
	'''
	def __init__(self, chisq, ref_ld, w_ld, N, M, num_blocks=200, non_negative=False,
		intercept=None, slow=False):
	
		self.N = N
		self.M = M
		self.M_tot = float(np.sum(M))
		self.n_annot = ref_ld.shape[1]
		self.n_snp = ref_ld.shape[0]
		self.mean_chisq = np.mean(chisq)
		self.constrain_intercept = intercept
		# median and matrix don't play nice?
		self.lambda_gc = np.median(np.asarray(chisq)) / 0.4549 
		ref_ld_tot = np.sum(ref_ld, axis=1)
		# dividing by mean N keeps the condition number under control
		Nbar = np.mean(N)
		self.Nbar = Nbar
		x = np.multiply(N, ref_ld) / Nbar
		if self.constrain_intercept is None:
			x = _append_intercept(x)	
			chisq_m_int = chisq - 1
		else:
			chisq_m_int = chisq - self.constrain_intercept
		
		agg_hsq = self._aggregate(chisq_m_int, np.multiply(N, ref_ld_tot), self.M_tot)
		weights = _hsq_weights(ref_ld_tot, w_ld, N, self.M_tot, agg_hsq) 
		if np.all(weights == 0):
			raise ValueError('Something is wrong, all regression weights are zero.')	
		
		x = _weight(x, weights)
		y = _weight(chisq_m_int, weights)
		self.w_mean_chisq = np.average(chisq, weights=weights)
		if non_negative:
			self._jknife = LstsqJackknifeSlow(x, y, num_blocks, nn=True)
		elif not slow: 
			self._jknife = LstsqJackknifeFast(x, y, num_blocks)
		else:
			self._jknife = LstsqJackknifeSlow(x, y, num_blocks)

		self.coef = self._jknife.est[0,0:self.n_annot] / Nbar
		self.coef_cov = self._jknife.jknife_cov[0:self.n_annot,0:self.n_annot] / (Nbar**2)
		self.coef_se = np.sqrt(np.diag(self.coef_cov))
		self.cat_hsq = np.multiply(self.M, self.coef)
		self.cat_hsq_cov = np.multiply(np.dot(self.M.T,self.M), self.coef_cov)
		self.cat_hsq_se = np.sqrt(np.diag(self.cat_hsq_cov))	
		self.tot_hsq = np.sum(self.cat_hsq)
		self.tot_hsq_cov = np.sum(self.cat_hsq_cov)
		self.tot_hsq_se = np.sqrt(self.tot_hsq_cov)	
		numer_delete_vals = np.multiply(self.M,self._jknife.delete_values[:,0:self.n_annot]) / Nbar
		denom_delete_vals = np.sum(numer_delete_vals,axis=1)*np.ones(self.n_annot) 
		prop_hsq_est = self.cat_hsq/self.tot_hsq
		self.prop_hsq_j = RatioJackknife(prop_hsq_est,numer_delete_vals,denom_delete_vals)
		self.prop_hsq = self.prop_hsq_j.est
		self.prop_hsq_se = self.prop_hsq_j.jknife_se
		self.prop_hsq_cov = self.prop_hsq_j.jknife_cov

		if intercept is None:
			self.intercept = self._jknife.est[0,self.n_annot] + 1
			self.intercept_se = self._jknife.jknife_se[0,self.n_annot]
			if self.mean_chisq > 1:
				self.ratio_se = self.intercept_se / (self.mean_chisq - 1)
				self.ratio = (self.intercept - 1) / (self.mean_chisq - 1)
			else:
				self.ratio = float('nan')
				self.ratio_se = float('nan')

		self.M_prop = self.M / self.M_tot
		self.enrichment = np.divide(self.cat_hsq, self.M) / (self.tot_hsq/self.M_tot)
		
	def _aggregate(self, y, x, M_tot):
		'''Aggregate estimator. For use in regression weights.'''
		numerator = np.mean(y)
		denominator = np.mean(x) / M_tot
		agg = numerator / denominator
		return agg

	def summary(self, ref_ld_colnames, overlap=False, outfile = None):
		'''Print information about LD Score Regression'''
		out = []
		out.append('Total observed scale h2: '+str(np.matrix(self.tot_hsq))+\
			' ('+str(np.matrix(self.tot_hsq_se))+')')
		if self.n_annot > 1:
			if not overlap:
				out.append( 'Categories: '+' '.join(ref_ld_colnames))
				out.append( 'Observed scale h2: '+ str(np.matrix(self.cat_hsq)))
				out.append( 'Observed scale h2 SE: '+str(np.matrix(self.cat_hsq_se)))
				out.append( 'Proportion of SNPs: '+str(np.matrix(self.M_prop)))
				out.append( 'Proportion of h2g: ' +str(np.matrix(self.prop_hsq)))
				out.append( 'Enrichment: '+str(np.matrix(self.enrichment)))	
				out.append( 'Coefficients: '+str(self.coef))
				out.append( 'Coefficient SE: '+str(self.coef_se))
			else:
				out.append( 'Partitioned heritabilities and enrichments printed to {}.results'.format(outfile))
		out.append( 'Lambda GC: '+ str(np.matrix(self.lambda_gc)))
		out.append( 'Mean Chi^2: '+ str(np.matrix(self.mean_chisq)))
		if self.constrain_intercept is not None:
			out.append( 'Intercept: constrained to {C}'.format(C=np.matrix(self.constrain_intercept)))
		else:
			out.append( 'Intercept: '+ str(np.matrix(self.intercept))+\
				' ('+str(np.matrix(self.intercept_se))+')')

		out = '\n'.join(out)
		return kill_brackets(out)
		
	def summary_intercept(self):
		'''Print information about LD Score regression intercept.'''
	
		out = []
		out.append( 'Observed scale h2: '+str(np.matrix(self.tot_hsq))+' ('+\
			str(np.matrix(self.tot_hsq_se))+')')
		out.append( 'Lambda GC: '+ str(np.matrix(self.lambda_gc)))
		out.append( 'Mean Chi^2: '+ str(np.matrix(self.mean_chisq)))
		out.append( 'Weighted Mean Chi^2: '+ str(np.matrix(self.w_mean_chisq)))
		out.append( 'Intercept: '+ str(np.matrix(self.intercept))+\
			' ('+str(np.matrix(self.intercept_se))+')')
		
		if self.mean_chisq > 1:
			out.append( 'Ratio: '+str(np.matrix(self.ratio))+\
				' ('+str(np.matrix(self.ratio_se))+')') 
		else:
			out.append( 'Ratio: NA (mean chi^2 < 1)' )
			
		out = '\n'.join(out)
		return kill_brackets(out)
	

class Gencov(object):
	
	'''
	Class for estimating genetic covariance / partitioned genetic covariance from summary 
	statistics.	Inherits from Hsq, but only for _aggregate. Note: the efficiency of the 
	estimate will be improved if first you estimate heritability for each trait then 
	feed these values into hsq1 and hsq2. This is only used for the regression weights. 
	
	Could probably refactor so as to reuse more code from Hsq, but (a) the amount of 
	duplicated code is small and (b) although the procedure for estimating genetic 
	covariance and h2 is now very similar, there is no guarantee that it will stay this
	way.
	
	Parameters
	----------
	bhat1, bhat2 : np.matrix with shape (n_snp, 1)
		(Signed) effect-size estimates for each study. In a case control study, bhat should be
		the signed square root of chi-square, where the sign is + if OR > 1 and - otherwise. 
	ld : np.matrix with shape (n_snp, n_annot) 
		LD Scores.
	w_ld : np.matrix with shape (n_snp, 1)
		LD Scores (non-partitioned) computed with sum r^2 taken over only those SNPs included 
		in the regression.
	N1, N2 :  np.matrix of ints > 0 with shape (n_snp, 1)
		Number of individuals sampled for each SNP for each study.
	M : int > 0
		Number of SNPs used for estimating LD Score (need not equal number of SNPs included in
		the regression).
	hsq1, hsq2 : float
		Heritability estimates for each study (used in regression weights).
	N_overlap : int, default 0.
		Number of overlapping samples.
	rho : float in [-1,1]
		Estimate of total phenotypic correlation between trait 1 and trait 2. Only used for 
		regression weights, and then only when N_overlap > 0. 	
	num_blocks : int, default = 1000
		Number of block jackknife blocks.
	intercept : none or float
		If none, fits LD Score regression w/ intercept. If float, constrains the intercept
		to equal the given float.
			
	Attributes
	----------
	N1, N2 : int
		Sample sizes. In a case/control study, this should be total sample size: number of 
		cases + number of controls. NOT some measure of effective sample size that accounts 
		for case/control ratio. The case-control ratio comes into play when converting from
		observed to liability scale (in the function obs_to_liab).
	gencov_cov : np.matrix with shape (n_annot, n_annot)
		Block jackknife estimate of variance-covariance matrix of the partitioned h2 estimates.
	cat_gencov : np.matrix with shape (1, n_annot)
	 	Partitioned heritability estimates.
	cat_gencov_se : np.matrix with shape (1, n_annot)
		Standard errors of partitioned heritability estimates.
	intercept : float
		LD Score regression intercept. NB this is not on the same scale as the intercept from
		the regression chisq ~ LD Score. The intercept from the genetic covariance regression
		is on the same scale as N_overlap / (N1*N2). 
	intercept_se : float
		Standard error of LD Score regression intercept.
	tot_gencov : float
		Total h2g estimate.
	tot_gencov_se : float
		Block jackknife estimate of standard error of the total h2g estimate. 
	prop_gencov : np.matrix with shape (1, n_annot)
		Proportion of genetic covariance per annotation.
	M_prop : np.matrix with shape (1, n_annot)
		Proportion of SNPs (in reference panel) per annotation. 
	enrichment : np.matrix with shape (1, n_annot)
		Per category enrichment of h2 relative to all SNPs. Precisely, 
		(gencov per SNP in category) / (gencov per SNP overall).
	_jknife : LstsqJackknife
		Jackknife object.
		
	'''
	def __init__(self, bhat1, bhat2, ref_ld, w_ld, N1, N2, M, hsq1, hsq2, N_overlap=None,
		rho=None, num_blocks=200, intercept=None, slow=False):
		
		self.N1 = N1
		self.N2 = N2
		self.N_overlap = N_overlap if N_overlap is not None else 0
		self.M = M
		self.M_tot = np.sum(M)
		self.n_annot = ref_ld.shape[1]
		self.n_snp = ref_ld.shape[0]
		self.constrain_intercept = intercept

		ref_ld_tot = np.sum(ref_ld, axis=1)
		n1n2 = float(np.dot(self.N1.T, self.N2))/self.n_snp
		y = np.multiply(bhat1, bhat2)
		if intercept is None:
			x = _append_intercept(ref_ld)
		else:
			x = ref_ld
			# input the intercept multiplied by N1*N2 for ease of use
			# internally work with betahat rather than Z score
			y = y - intercept/n1n2
			rho = 1
			N_overlap = intercept
		
		agg_gencov = self._aggregate(y, ref_ld_tot, self.M_tot, rho, N_overlap)
		weights = _gencov_weights(ref_ld_tot, w_ld, N1, N2, N_overlap, self.M_tot, hsq1, hsq2, 
			agg_gencov, rho) 
		if np.all(weights == 0):
			raise ValueError('Something is wrong, all regression weights are zero.')	
	
		x = _weight(x, weights)
		y = _weight(y, weights)
		
		if not slow: 
			self._jknife = LstsqJackknifeFast(x, y, num_blocks)
		else:
			self._jknife = LstsqJackknifeSlow(x, y, num_blocks)

		no_intercept_cov = self._jknife.jknife_cov[0:self.n_annot,0:self.n_annot]
		self.gencov_cov = np.multiply(np.dot(self.M.T,self.M), no_intercept_cov)
		self.coef = self._jknife.est[0,0:self.n_annot]
		self.coef_se = np.sqrt(np.diag(no_intercept_cov))
		self.cat_gencov = np.multiply(self.M, self._jknife.est[0,0:self.n_annot])
		self.cat_gencov_se = np.multiply(self.M, self._jknife.jknife_se[0,0:self.n_annot])	
		self.tot_gencov = np.sum(self.cat_gencov)
		self.tot_gencov_se = np.sqrt(np.sum(M*no_intercept_cov*self.M.T))
		self.prop_gencov = self.cat_gencov / self.tot_gencov
		self.M_prop = self.M / self.M_tot
		self.enrichment = np.divide(self.cat_gencov, self.M) / (self.tot_gencov/self.M_tot)
		self.Z = self.tot_gencov / self.tot_gencov_se
		self.P_val = chi2.sf(self.Z**2, 1, loc=0, scale=1)
		if intercept is None:
			self.intercept = self._jknife.est[0,self.n_annot]*n1n2
			self.intercept_se = self._jknife.jknife_se[0,self.n_annot]*n1n2

	def _aggregate(self, y, x, M_tot, rho=None, N_overlap=None):
		'''Aggregate estimator. For use in regression weights.'''
		numerator = np.mean(y)
		denominator = np.mean(x) / M_tot
		agg = numerator / denominator
		return agg
	
	def summary(self, ref_ld_colnames, overlap=False):
		'''Print output of jk.Gencov object'''
		out = []
		out.append('Total observed scale gencov: '+str(np.matrix(self.tot_gencov))+' ('+\
			str(np.matrix(self.tot_gencov_se))+')')
		out.append('Z-score: '+str(np.matrix(self.Z)))
		out.append('P: '+str(np.matrix(self.P_val)))		

		if self.n_annot > 1:
			out.append( 'Categories: '+ str(' '.join(ref_ld_colnames)))
			if not overlap:
				out.append( 'Observed scale gencov: '+str(np.matrix(self.cat_gencov)))
				out.append( 'Observed scale gencov SE: '+str(np.matrix(self.cat_gencov_se)))
				out.append( 'Proportion of SNPs: '+str(np.matrix(self.M_prop)))
				out.append( 'Proportion of gencov: ' +str(np.matrix(self.prop_gencov)))
				out.append( 'Enrichment: '+str(np.matrix(self.enrichment)))
		
		if self.constrain_intercept is not None:
			out.append( 'Intercept: constrained to {C}'.format(C=np.matrix(self.constrain_intercept)))
		else:
			out.append( 'Intercept: '+ str(np.matrix(self.intercept))+\
				' ('+str(np.matrix(self.intercept_se))+')')

		out = '\n'.join(out)
		return kill_brackets(out)
	
	
class Gencor(object):

	'''
	Class for estimating genetic correlation from summary statistics. Implemented as a ratio
	estimator with block jackknife bias correction (the block jackknife allows for 
	estimation of reasonably good standard errors from dependent data and decreases the 
	bias in a ratio estimate from O(1/N) to O(1/N^2), where N = number of data points). 
	
	Parameters
	----------
	bhat1, bhat2 : np.matrix with shape (n_snp, 1)
		(Signed) effect-size estimates for each study. In a case control study, bhat should be
		the signed square root of chi-square, where the sign is + if OR > 1 and - otherwise. 
	ld : np.matrix with shape (n_snp, n_annot) 
		LD Scores.
	w_ld : np.matrix with shape (n_snp, 1)
		LD Scores (non-partitioned) computed with sum r^2 taken over only those SNPs included 
		in the regression.
	N1, N2 :  np.matrix of ints > 0 with shape (n_snp, 1)
		Number of individuals sampled for each SNP for each study.
	M : int > 0
		Number of SNPs used for estimating LD Score (need not equal number of SNPs included in
		the regression).
	hsq1, hsq2 : float
		Heritability estimates for each study (used in regression weights).
	N_overlap : int, default 0.
		Number of overlapping samples.
	rho : float in [-1,1]
		Estimate of total phenotypic correlation between trait 1 and trait 2. Only used for 
		regression weights, and then only when N_overlap > 0. 	
	num_blocks : int, default = 1000
		Number of block jackknife blocks.
	intercepts : list with length 3
		Intercepts for constrained LD Score regression. If None, then do not constrain 
		intercept. 
	
	Attributes
	----------
	N1, N2 : int
		Sample sizes. In a case/control study, this should be total sample size: number of 
		cases + number of controls. NOT some measure of effective sample size that accounts 
		for case/control ratio. The case-control ratio comes into play when converting from
		observed to liability scale (in the function obs_to_liab).
	M : np.matrix of ints with shape (1, n_annot)
		Total number of SNPs per category in the reference panel used for estimating LD Score.
	M_tot : int
		Total number of SNPs in the reference panel used for estimating LD Score.
	n_annot : int
		Number of partitions.
	n_snp : int
		Number of SNPs included in the regression.	
	hsq1, hsq2 : Hsq
		Heritability estimates for traits 1 and 2, respectively.
	gencov : Gencov
		Genetic covariance estimate.
	autocor : float
		Lag-1 autocorrelation between ratio block jackknife pseudoerrors. If much above zero, 
		the block jackknife standard error will be unreliable. This can be solved by using a 
		larger block size.
	tot_gencor : float
		Total genetic correlation. 
	tot_gencor_se : float
		Genetic correlation standard error.
	_gencor : RatioJackknife
		Jackknife used for estimating genetic correlation. 

	'''
	def __init__(self, bhat1, bhat2, ref_ld, w_ld, N1, N2, M, intercepts, 
		N_overlap=None,	rho=None, num_blocks=200, return_silly_things=False, first_hsq=None,
		slow=False):

		self.N1 = N1
		self.N2 = N2
		self.N_overlap = N_overlap if N_overlap is not None else 0
		self.rho = rho if rho is not None else 0
		self.M = M
		self.M_tot = np.sum(M)
		self.n_annot = ref_ld.shape[1]
		self.n_snp = ref_ld.shape[0]		
		self.intercepts = intercepts
		self.huge_se_flag = False
		self.negative_hsq_flag = False
		self.out_of_bounds_flag = False
		self.tiny_hsq_flag = False
		self.return_silly_things = return_silly_things
		chisq1 = np.multiply(N1, np.square(bhat1))
		chisq2 = np.multiply(N2, np.square(bhat2))
		
		if first_hsq is None:
			self.hsq1 = Hsq(chisq1, ref_ld, w_ld, N1, M, num_blocks=num_blocks, 
				non_negative=False, intercept=intercepts[0], slow=slow)
		else:
			self.hsq1 = first_hsq
			
		self.hsq2 = Hsq(chisq2, ref_ld, w_ld, N2, M, num_blocks=num_blocks, 
			non_negative=False, intercept=intercepts[1], slow=slow)	
		self.gencov = Gencov(bhat1, bhat2, ref_ld, w_ld, N1, N2, M, self.hsq1.tot_hsq,
			self.hsq2.tot_hsq, N_overlap=self.N_overlap, rho=self.rho, num_blocks=num_blocks,
			intercept=intercepts[2], slow=slow)
		
		if (self.hsq1.tot_hsq <= 0 or self.hsq2.tot_hsq <= 0):
			self.negative_hsq_flag = True
			
		# total genetic correlation
		self.tot_gencor_biased = self.gencov.tot_gencov /\
			np.sqrt(self.hsq1.tot_hsq * self.hsq2.tot_hsq)
		numer_delete_values = self.cat_to_tot(self.gencov._jknife.delete_values[:,0:self.n_annot], self.M)
		hsq1_delete_values = self.cat_to_tot(self.hsq1._jknife.delete_values[:,0:self.n_annot], self.M)\
			/ self.hsq1.Nbar
		hsq2_delete_values = self.cat_to_tot(self.hsq2._jknife.delete_values[:,0:self.n_annot], self.M)\
			/ self.hsq2.Nbar
		denom_delete_values = np.sqrt(np.multiply(hsq1_delete_values, hsq2_delete_values))
		self.gencor = RatioJackknife(self.tot_gencor_biased, numer_delete_values, denom_delete_values)
		self.tot_gencor = float(self.gencor.jknife_est)
		if (self.tot_gencor > 1.2 or self.tot_gencor < -1.2):
			self.out_of_bounds_flag = True	
		elif np.isnan(self.tot_gencor):
			self.tiny_hsq_flag = True
			
		self.tot_gencor_se = float(self.gencor.jknife_se)
		if self.tot_gencor_se > 0.25:
			self.huge_se_flag	 = True
		
		self.Z = self.tot_gencor / self.tot_gencor_se
		self.P_val = chi2.sf(self.Z**2, 1, loc=0, scale=1)

	def cat_to_tot(self, x, M):
		'''Converts per-category pseudovalues to total pseudovalues.'''
		return np.dot(x, M.T)
	
	def summary(self):
		'''Reusable code for printing output of jk.Gencor object'''
		out = []
		
		if self.negative_hsq_flag and not self.return_silly_things:
			out.append('Genetic Correlation: nan (nan) (heritability estimate < 0) ')
			out.append('Z-score: nan (nan) (heritability estimate < 0)')
			out.append('P: nan (nan) (heritability estimate < 0)')
			out.append('WARNING: One of the h2 estimates was < 0. Consult the documentation.')
			out = '\n'.join(out)

		elif self.tiny_hsq_flag and not self.return_silly_things:
			out.append('Genetic Correlation: nan (nan) (heritability close to 0) ')
			out.append('Z-score: nan (nan) (heritability close to 0)')
			out.append('P: nan (nan) (heritability close to 0)')
			out.append('WARNING: one of the h2\'s was < 0 in one of the jackknife blocks. Consult the documentation.')
			out = '\n'.join(out)
		
		elif self.huge_se_flag and not self.return_silly_things:
			warn_msg = ' WARNING: asymptotic P-values may not be valid when SE(rg) is very high.'
			out.append('Genetic Correlation: '+str(np.matrix(self.tot_gencor))+' ('+\
				str(np.matrix(self.tot_gencor_se))+')')
			out.append('Z-score: '+str(np.matrix(self.Z)))
			out.append('P: '+str(np.matrix(self.P_val))+warn_msg)	
			out = '\n'.join(out)
			
		elif self.out_of_bounds_flag and not self.return_silly_things:
			out.append('Genetic Correlation: nan (nan) (rg out of bounds) ')
			out.append('Z-score: nan (nan) (rg out of bounds)')
			out.append('P: nan (nan) (rg out of bounds)')
			out.append('WARNING: rg was out of bounds. Consult the documentation.')
			out = '\n'.join(out)
			
		else:		
			out.append('Genetic Correlation: '+str(np.matrix(self.tot_gencor))+' ('+\
				str(np.matrix(self.tot_gencor_se))+')')
			out.append('Z-score: '+str(np.matrix(self.Z)))
			out.append('P: '+str(np.matrix(self.P_val)))		
			if self.return_silly_things and \
				(self.huge_se_flag or self.negative_hsq_flag or self.out_of_bounds_flag or self.tiny_hsq_flag):
				out.append('WARNING: returning silly results because you asked for them.')
			out = '\n'.join(out)
			
		return kill_brackets(out)