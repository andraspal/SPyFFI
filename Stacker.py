'''Tools to stack images, using a variety of algorithms
    (independent from Strategies, to optimize for 2D images).'''

from imports import *


def pick(name='Sum'):
    '''Based on an input name, return a stacker object.'''
    if 'Central' in name:
        bits = name.split()
        m, n = np.int(bits[1]), np.int(bits[-1])
        return SumOfTruncatedMean(n=n, m=m)
    if 'Rejecting' in name:
        bits = name.split()
        #threshold, n, memory = np.float(bits[1]), np.float(bits[7]), np.float(bits[10])
        return SumWithOutlierRejection(threshold=10, n=10, memory=0.5)



class Stacker(Talker):
    '''Stack a cube of images, using some filter.'''

    def __init__(self, **kwargs):
        # decide whether or not this Stacker is chatty
        Talker.__init__(self, **kwargs)

    def stackCosmics(self, cube):
        pass

class SumWithOutlierRejection(Stacker):
    '''Binning with TruncatedMean = break into subsets, reject the highest and lowest points from each and take the mean of the rest, sum these truncated means.'''
    def __init__(self, n=10, threshold=10.0, memory=0.90, safetybuffer=2.0, diagnostics=False):
        '''Initialize an outlierwith decay Strategy.

        n = the number of subexposures in each "chunk"
        threshold = how many sigma about the noise are required for a point to be an outlier?
        memory = the weight given to previous estimates of standard deviations (best estimate = memory[previous best estimate] + (1 - memory)[most recent chunk])
        safetybuffer = by what factor should we inflate the initial standard deviation to prevent overfitting?'''

        Stacker.__init__(self)
        self.n = n

        # store the parameters of the filter
        self.threshold = threshold
        self.memory = memory
        self.safetybuffer = safetybuffer

        # define a name for this filter
        self.name = 'Rejecting {threshold} sigma Outliers with chunks of {n} and memory of {memory}'.format(threshold=self.threshold, memory=self.memory, n=self.n)

        # for testing, keep a diagnostics flag to say whether to display the mean + std. estimates
        self.diagnostics = diagnostics

    def stack(self, cube, nsubexposures):

        # figure out the original shape
        xpixels, ypixels, subexposures = cube.photons.shape
        exposures = subexposures/nsubexposures
        assert(subexposures % nsubexposures == 0)
        assert(nsubexposures % self.n == 0)
        assert(self.n > 3)

        # reshape into something more convenient for summing
        unsplit = cube.photons
        splitintosubexposures = cube.photons.reshape(xpixels, ypixels, exposures, nsubexposures)
        nchunks = nsubexposures/self.n
        splitintochunks = splitintosubexposures.reshape(xpixels, ypixels, exposures, nchunks, self.n)

        # create an array to store the final binned timeseries
        finaltimeseries = np.zeros((xpixels, ypixels, exposures))

        try:
            self.running_mean
            self.running_std
            self.juststarted = False
            #self.speak('USING A RUNNING MEAN THAT WAS ALREADY CALCULATED!')
        except:
            # create arrays to store the per-chunk estimates of the mean and the standard deviation
            self.running_mean, self.running_std = np.zeros((xpixels, ypixels)), np.zeros((xpixels, ypixels))

            # initialize these estimates with the first chunk (rejecting no outliers)

            self.running_mean[:,:] = np.mean(unsplit[:,:,0:self.n], -1)
            self.running_std[:,:] = np.sqrt(np.sum((unsplit[:,:,0:self.n] - self.running_mean[:,:].reshape(xpixels,ypixels,1))**2,-1))#/(n-1.0))

            # inflate the initial standard deviation measurement to prevent overfitting
            self.running_std[:,:] *= self.safetybuffer

            self.running_std[:,:] = np.maximum(self.running_std, np.sqrt(self.running_mean))
            self.juststarted = True


        # loop over the binned exposures, and chunks within exposures
        count = 1
        for iexposure in np.arange(exposures):
          for ichunk in np.arange(nchunks):



            # pull out the light curve for this little chunk
            flux = splitintochunks[:,:,iexposure, ichunk,:].squeeze()

            # pull out the last mean and standard deviation estimates
            best_mean = self.running_mean[:,:] + 0
            best_std = self.running_std[:,:] + 0

            # determine which points are not outliers, by being less than [threshold] sigma over the mean
            notoutlier = flux < (best_mean + self.threshold*best_std).reshape(xpixels, ypixels, 1)

            # if all the images are outliers, decide that none of them are
            fail = np.sum(notoutlier,-1) == 0
            notoutlier[fail.reshape(xpixels, ypixels),:] = True

            if self.juststarted:
                notoutlier[:,:,:] = True
                self.juststarted = False

            # determine the mean and standard deviation of the good points in this chunk
            this_mean = np.sum(flux*notoutlier,-1)/np.sum(notoutlier,-1)
            this_std = np.sqrt(np.sum((flux - this_mean.reshape(xpixels,ypixels,1))**2*notoutlier, -1)/np.sum(notoutlier,-1))#/(n - 1.0))
            this_std = np.maximum(this_std, np.sqrt(self.running_mean))

            # store this binned exposure in the final array
            finaltimeseries[:,:,iexposure] += this_mean*self.n

            # mix this chunk into the self.running estimates, for the next chunk to use
            self.running_mean[:,:] = self.memory*best_mean + (1.0 - self.memory)*this_mean
            self.running_std[:,:] = self.memory*best_std + (1.0 - self.memory)*this_std
            # or would it be better to be doing this in variance space?, such as...
            # self.running_std[iexposure, ichunk] = np.sqrt(self.memory*best_std**2 + (1.0 - self.memory)*this_std**2)

            assert(np.isfinite(self.running_mean).all() & np.isfinite(self.running_std).all())
            # advance the linear counter
            count += 1
        photons = finaltimeseries

        #cube.display(self.running_mean)
        #cube.ds9.one(self.running_std, clobber=False)
        # sum the cosmics
        cosmics = np.sum(cube.cosmics.reshape(xpixels, ypixels, exposures, nsubexposures), -1)

        # sum the noiseless image
        noiseless = np.sum(cube.noiseless.reshape(xpixels, ypixels, exposures, nsubexposures), -1)

        # sum the unmitigated image
        unmitigated = np.sum(cube.photons.reshape(xpixels, ypixels, exposures, nsubexposures), -1)
        assert((unmitigated > 1).all())

        return photons.squeeze(), cosmics.squeeze(), noiseless.squeeze(), unmitigated.squeeze()


class SumWithHybrid(Stacker):
    '''Binning with TruncatedMean = break into subsets, reject the highest and lowest points from each and take the mean of the rest, sum these truncated means.'''
    def __init__(self, n=10, threshold=10.0, memory=0.50, safetybuffer=2.0, diagnostics=False):
        '''Initialize an outlierwith decay Strategy.

        n = the number of subexposures in each "chunk"
        threshold = how many sigma about the noise are required for a point to be an outlier?
        memory = the weight given to previous estimates of standard deviations (best estimate = memory[previous best estimate] + (1 - memory)[most recent chunk])
        safetybuffer = by what factor should we inflate the initial standard deviation to prevent overfitting?'''

        Stacker.__init__(self)
        self.n = n

        # store the parameters of the filter
        self.threshold = threshold
        self.memory = memory
        self.safetybuffer = safetybuffer

        # define a name for this filter
        self.name = 'Hybrid with Memory of {memory} and Threshold of {threshold} sigma'.format(threshold=self.threshold, memory=self.memory, n=self.n)

        # for testing, keep a diagnostics flag to say whether to display the mean + std. estimates
        self.diagnostics = diagnostics

    def stack(self, cube, nsubexposures):

        # figure out the original shape
        xpixels, ypixels, subexposures = cube.photons.shape
        exposures = subexposures/nsubexposures
        assert(subexposures % nsubexposures == 0)
        assert(nsubexposures % self.n == 0)
        assert(self.n > 3)

        # reshape into something more convenient for summing
        unsplit = cube.photons
        splitintosubexposures = cube.photons.reshape(xpixels, ypixels, exposures, nsubexposures)
        nchunks = nsubexposures/self.n
        splitintochunks = splitintosubexposures.reshape(xpixels, ypixels, exposures, nchunks, self.n)

        # create an array to store the final binned timeseries
        finaltimeseries = np.zeros((xpixels, ypixels, exposures))

        try:
            self.running_mean
            self.running_std

            #self.speak('USING A RUNNING MEAN THAT WAS ALREADY CALCULATED!')
        except:
            # create arrays to store the per-chunk estimates of the mean and the standard deviation
            self.running_mean, self.running_std = np.zeros((xpixels, ypixels)), np.zeros((xpixels, ypixels))

            # initialize these estimates with the first chunk (rejecting no outliers)

            self.running_mean[:,:] = np.mean(unsplit[:,:,0:self.n], -1)
            self.running_std[:,:] = np.sqrt(np.sum((unsplit[:,:,0:self.n] - self.running_mean[:,:].reshape(xpixels,ypixels,1))**2,-1))#/(n-1.0))

            # inflate the initial standard deviation measurement to prevent overfitting
            self.running_std[:,:] *= self.safetybuffer

            self.running_std[:,:] = np.maximum(self.running_std, np.sqrt(self.running_mean))

        # set the first binned point to this mean estimate (there's no other choice)
        finaltimeseries[:,:,0] = self.running_mean[:,:]

        # loop over the binned exposures, and chunks within exposures
        count = 1
        for iexposure in np.arange(exposures):
          for ichunk in np.arange(nchunks):

            # skip the very first point, because it's already been defined
            if (ichunk == 0)&(iexposure == 0):
              continue

            # pull out the light curve for this little chunk
            flux = splitintochunks[:,:,iexposure, ichunk,:].squeeze()

            # pull out the last mean and standard deviation estimates
            best_mean = self.running_mean[:,:] + 0
            best_std = self.running_std[:,:] + 0

            # determine which points are not outliers, by being less than [threshold] sigma over the mean
            notoutlier = flux < (best_mean + self.threshold*best_std).reshape(xpixels, ypixels, 1)

            # if all the images are outliers, decide that none of them are
            fail = np.sum(notoutlier,-1) == 0
            notoutlier[fail.reshape(xpixels, ypixels),:] = True

            # determine the mean and standard deviation of the good points in this chunk
            this_mean = np.sum(flux*notoutlier,-1)/np.sum(notoutlier,-1)
            this_std = np.sqrt(np.sum((flux - this_mean.reshape(xpixels,ypixels,1))**2*notoutlier, -1)/np.sum(notoutlier,-1))#/(n - 1.0))
            this_std = np.maximum(this_std, np.sqrt(self.running_mean))

            # store this binned exposure in the final array
            finaltimeseries[:,:,iexposure] += this_mean*self.n

            # mix this chunk into the self.running estimates, for the next chunk to use
            self.running_mean[:,:] = self.memory*best_mean + (1.0 - self.memory)*this_mean
            self.running_std[:,:] = self.memory*best_std + (1.0 - self.memory)*this_std
            # or would it be better to be doing this in variance space?, such as...
            # self.running_std[iexposure, ichunk] = np.sqrt(self.memory*best_std**2 + (1.0 - self.memory)*this_std**2)

            assert(np.isfinite(self.running_mean).all() & np.isfinite(self.running_std).all())
            # advance the linear counter
            count += 1
        photons = finaltimeseries

        cube.display(self.running_mean)
        cube.ds9.one(self.running_std, clobber=False)
        # sum the cosmics
        cosmics = np.sum(cube.cosmics.reshape(xpixels, ypixels, exposures, nsubexposures), -1)

        # sum the noiseless image
        noiseless = np.sum(cube.noiseless.reshape(xpixels, ypixels, exposures, nsubexposures), -1)

        # sum the unmitigated image
        unmitigated = np.sum(cube.photons.reshape(xpixels, ypixels, exposures, nsubexposures), -1)
        assert((unmitigated > 1).all())

        return photons.squeeze(), cosmics.squeeze(), noiseless.squeeze(), unmitigated.squeeze()





class SumOfTruncatedMean(Stacker):
    '''Binning with TruncatedMean = break into subsets, reject the highest and lowest points from each and take the mean of the rest, sum these truncated means.'''
    def __init__(self, n=10, m=None):
        Stacker.__init__(self)
        self.n = n
        if m is None:
            self.m = self.n-2
        else:
            self.m = m
            assert(((self.n - self.m) % 2) == 0)
        self.name = "Central {m} out of {n}".format(m = self.m, n=self.n)

    def stack(self, cube, nsubexposures):
        assert(self.n - self.m == 2)

        # figure out the original shape
        xpixels, ypixels, subexposures = cube.photons.shape
        exposures = subexposures/nsubexposures
        assert(subexposures % nsubexposures == 0)

        # reshape into something more convenient for summing
        splitintosubexposures = cube.photons.reshape(xpixels, ypixels, exposures, nsubexposures)
        splitintochunks = splitintosubexposures.reshape(xpixels, ypixels, exposures, nsubexposures/self.n, self.n)

        # calculate the sum of the truncated means (and recalibrate to the original scale!!!)
        sum = np.sum(splitintochunks, -1)
        min = np.min(splitintochunks, -1)
        max = np.max(splitintochunks, -1)
        photons = np.sum(sum - max - min, -1)*self.n/self.m

        # sum the cosmics
        cosmics = np.sum(cube.cosmics.reshape(xpixels, ypixels, exposures, nsubexposures), -1)

        # sum the noiseless image
        noiseless = np.sum(cube.noiseless.reshape(xpixels, ypixels, exposures, nsubexposures), -1)

        # sum the unmitigated image
        unmitigated = np.sum(sum, -1)
        assert((unmitigated > 1).all())

        return photons.squeeze(), cosmics.squeeze(), noiseless.squeeze(), unmitigated.squeeze()