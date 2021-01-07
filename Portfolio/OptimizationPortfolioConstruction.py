from clr import AddReference
AddReference("QuantConnect.Common")
AddReference("QuantConnect.Algorithm.Framework")

from QuantConnect import Resolution, Extensions
from QuantConnect.Algorithm.Framework.Alphas import *
from QuantConnect.Algorithm.Framework.Portfolio import *
from itertools import groupby
from datetime import datetime, timedelta
from pytz import utc
UTCMIN = datetime.min.replace(tzinfo=utc)
UTCMAX = datetime.max.replace(tzinfo=utc)

from optimizer import CustomPortfolioOptimizer
import numpy as np
import pandas as pd

class OptimizationPortfolioConstructionModel(PortfolioConstructionModel):
    
    '''
    Description:
        Allocate optimal weights to each security in order to optimize the portfolio objective function provided
    Details:
        - Two Canary Assets determine how much to invest in Risky Assets:
            If both assets have positive absolute momentum => 100%
            If only one has positive absolute momentum => 50%
            If none have positive absolute momentum => 0%
            * The remaining % from the above calculation will go to the Crash Protection Ticker, only if it has positive absolute momentum
        - To calculate the weights for risky assets, we perform portfolio optimization with the following particularity:
            We construct the correlation matrix using a 1-3-6-12 momentum weighting:
            ( last month correlation * 12 + last 3-month correlation * 4 + last 6-month correlation * 2 + last 12-month correlation ) / 19
    '''
    
    def __init__(self, crashProtectionTicker, canaryTickers, topMomentum, objectiveFunction = 'std', rebalancingPeriod = Expiry.EndOfMonth):
        
        self.crashProtectionTicker = crashProtectionTicker # this ticker will also be part of momentum asset allocation,
                                                            # but it's a special asset that will get the crash protection allocation when needed
        self.canaryTickers = canaryTickers # canary tickers to avoid in momentum calculations, but we need to subscribe to them
        self.topMomentum = topMomentum # number of top momentum securities to keep
        self.rebalancingPeriod = rebalancingPeriod # the rebalancing function
        self.optimizer = CustomPortfolioOptimizer(minWeight = 0, maxWeight = 1, objFunction = objectiveFunction) # initialize the optimizer
        self.insightCollection = InsightCollection()
        self.nextExpiryTime = UTCMAX
        
        self.rebalancingTime = None

    def CreateTargets(self, algorithm, insights):
        
        '''
        Description:
            Create portfolio targets from the specified insights
        Args:
            algorithm: The algorithm instance
            insights: The insights to create portoflio targets from
        Returns:
            An enumerable of portoflio targets to be sent to the execution model
        '''
        
        if self.rebalancingTime is None:
            # get next rebalancing time
            self.rebalancingTime = self.rebalancingPeriod(algorithm.Time)
            
        targets = []
        
        # check if we have new insights coming from the alpha model or if some existing insights have expired
        if len(insights) == 0 and algorithm.UtcTime <= self.nextExpiryTime:
            return targets

        # here we get the new insights and add them to our insight collection
        for insight in insights:
            self.insightCollection.Add(insight)
        
        # get insight that haven't expired of each symbol that is still in the universe
        activeInsights = self.insightCollection.GetActiveInsights(algorithm.UtcTime)
    
        # get the last generated active insight for each symbol
        lastActiveInsights = []
        for symbol, g in groupby(activeInsights, lambda x: x.Symbol):
            lastActiveInsights.append(sorted(g, key = lambda x: x.GeneratedTimeUtc)[-1])
        
        # symbols with active insights
        lastActiveSymbols = [x.Symbol for x in lastActiveInsights]
        
        ### calculate targets -------------------------------------------------------------------------------------
        
        if self.ShouldCreateTargets(algorithm, lastActiveSymbols):
            algorithm.Log('(Portfolio) time to calculate the targets')
            algorithm.Log('(Portfolio) number of active insights: ' + str(len(lastActiveSymbols)))
            
            ### get symbols ---------------------------------------------------------------------------------------
            
            # top momentum symbols
            topMomentumSymbols = [x.Symbol for x in lastActiveInsights]
            
            # crash protection symbol
            crashProtectionSymbol = [x.Symbol for x in algorithm.ActiveSecurities.Values if x.Symbol.Value in self.crashProtectionTicker]
    
            # if active symbols are more than topMomentum, we need to remove the crashProtectionSymbol from topMomentumSymbols
            if len(lastActiveSymbols) > self.topMomentum:
                if crashProtectionSymbol[0] in topMomentumSymbols:
                    topMomentumSymbols.remove(crashProtectionSymbol[0])
                else:
                    algorithm.Log('(Portfolio) lastActiveSymbols is bigger than topMomentum, but crashProtectionSymbol is not in topMomentumSymbols!')
                
            # canary symbols
            canarySymbols = [x.Symbol for x in algorithm.ActiveSecurities.Values if x.Symbol.Value in self.canaryTickers]
            
            # combine the two lists to get all symbols for calculations
            allSymbols = topMomentumSymbols + canarySymbols
            
            ### ----------------------------------------------------------------------------------------------------
            
            # get historical data for all symbols
            history = algorithm.History(allSymbols, 253, Resolution.Daily)
            
            # empty dictionary for calculations
            calculations = {}
            
            # iterate over all symbols and perform calculations
            for symbol in allSymbols:
                if (str(symbol) not in history.index or history.loc[str(symbol)].get('close') is None
                or history.loc[str(symbol)].get('close').isna().any()):
                    algorithm.Log('(Portfolio) no historical data for: ' + str(symbol.Value))
                    if symbol in lastActiveSymbols:
                        lastActiveSymbols.remove(symbol)
                    continue
                else:
                    # add symbol to calculations
                    calculations[symbol] = SymbolData(symbol)
                    try:
                        # get momentum score
                        calculations[symbol].CalculateMomentumScore(history)
                    except Exception:
                        algorithm.Log('(Portfolio) removing from Portfolio calculations due to CalculateMomentumScore failing')
                        calculations.pop(symbol)
                        if symbol in lastActiveSymbols:
                            lastActiveSymbols.remove(symbol)
                        continue
                
            # calculate the percentage of aggressive allocation for risky assets
            pctAggressive = self.CalculatePctAggressive(calculations, canarySymbols)
            algorithm.Log('(Portfolio) pctAggressive: ' + str(pctAggressive))
            
            # calculate optimal weights
            optWeights = self.DetermineTargetPercent(calculations, topMomentumSymbols, crashProtectionSymbol)
            
            if not optWeights.isnull().values.any():
                algorithm.Log('(Portfolio) optimal weights: ' + str(optWeights))
                
                # apply percentage aggressive to the weights to get final weights
                finalWeights = optWeights * pctAggressive
                algorithm.Log('(Portfolio) final weights: ' + str(finalWeights))
                
                # iterate over active symbols and create targets
                for symbol in lastActiveSymbols:
                    # we allocate the rest to the crash protection asset
                    if symbol in crashProtectionSymbol and pctAggressive < 1:
                        finalWeights[str(symbol)] = finalWeights[str(symbol)] + (1 - pctAggressive)
                        
                        algorithm.Log('(Portfolio) adding ' + str(1 - pctAggressive) + ' extra weight for ' + str(symbol.Value)
                        + '; final weight: ' + str(finalWeights[str(symbol)]))
                        
                    weight = finalWeights[str(symbol)]
                    target = PortfolioTarget.Percent(algorithm, symbol, weight)
                    algorithm.Plot('Chart Optimal Weights %', symbol.Value, float(finalWeights[str(symbol)]))
                    
                    if not target is None:
                        targets.append(target)
                        
        ### end of calculations --------------------------------------------------------------------------------
                    
        # get expired insights and create flatten targets for each symbol
        expiredInsights = self.insightCollection.RemoveExpiredInsights(algorithm.UtcTime)
        
        expiredTargets = []
        for symbol, f in groupby(expiredInsights, lambda x: x.Symbol):
            if not self.insightCollection.HasActiveInsights(symbol, algorithm.UtcTime):
                expiredTargets.append(PortfolioTarget(symbol, 0))
                continue
            
        targets.extend(expiredTargets)
        
        # here we update the next expiry date in the insight collection
        self.nextExpiryTime = self.insightCollection.GetNextExpiryTime()
        if self.nextExpiryTime is None:
            self.nextExpiryTime = UTCMIN
            
        return targets
        
    def ShouldCreateTargets(self, algorithm, lastActiveSymbols):
        
        '''
        Description:
            Determine whether we should create new portfolio targets when:
                - It's time to rebalance and there are active insights
        Args:
            lastActiveSymbols: Symbols for the last active securities
        '''
        
        if algorithm.Time >= self.rebalancingTime and len(lastActiveSymbols) > 0:
            # update rebalancing time
            self.rebalancingTime = self.rebalancingPeriod(algorithm.Time)
            return True
        else:
            return False
        
    def CalculatePctAggressive(self, calculations, canarySymbols):
        
        '''
        Description:
            Calculate the percentage dedicated to risky assets
        Args:
            calculations: Dictionary with calculations for symbols
            canarySymbols: Symbols for the canary assets
        Returns:
            Float with the percentage dedicated to risky assets
        '''
        
        # get a list with the canary assets that have positive absolute momentum
        canaryPosMomList = list(filter(lambda x: x.momentumScore > 0 and x.Symbol in canarySymbols, calculations.values()))
        
        # get the average positive (basically the options are 0, 0.5 or 1)
        # this will be the allocation for risky assets
        pctAggressive = len(canaryPosMomList) / len(canarySymbols)
        
        return pctAggressive
    
    def DetermineTargetPercent(self, calculations, topMomentumSymbols, crashProtectionSymbol):
        
        '''
        Description:
            Determine the target percent for each symbol provided
        Args:
            calculations: Dictionary with calculations for symbols
            topMomentumSymbols: Symbols for the top momentum assets
            crashProtectionSymbol: Symbol for the crash protection asset
        Returns:
            Pandas series with the optimal weights for each symbol
        '''
        
        # create a dictionary keyed by the symbols in calculations with a pandas.Series as value to create a dataframe of log-returns
        logReturnsDict = { str(symbol): np.log(1 + symbolData.returnSeries) for symbol, symbolData in calculations.items() if symbol in topMomentumSymbols }
        logReturnsDf = pd.DataFrame(logReturnsDict)
        
        # create correlation matrix with 1-3-6-12 momentum weighting
        corrMatrix = ( logReturnsDf.tail(21).corr() * 12 + logReturnsDf.tail(63).corr() * 4 + logReturnsDf.tail(126).corr() * 2 + logReturnsDf.tail(252).corr() ) / 19
        
        # create standard deviation matrix using the 1-month standard deviation of returns
        stdMatrix = pd.DataFrame(logReturnsDf.tail(21).std()) # column vector (one row per symbol and one single column with the standard deviation)
        # get its transpose
        stdMatrixTranspose = stdMatrix.T # row vector (one single row with the standard deviation and one column per symbol)
        
        # compute the dot product between stdMatrix and its transpose to get the volatility matrix
        volMatrix = stdMatrix.dot(stdMatrixTranspose) # square NxN matrix with the variances of each symbol on the diagonal and the product of stds on the off diagonal
        
        # calculate the covariance matrix by doing element-wise multiplication of correlation matrix and volatility matrix
        covMatrix = corrMatrix.multiply(volMatrix)
        
        # portfolio optimizer finds the optimal weights for the given data
        weights = self.optimizer.Optimize(historicalLogReturns = logReturnsDf, covariance = covMatrix)
        weights = pd.Series(weights, index = logReturnsDf.columns)
        
        # avoid very small numbers and make them 0
        for symbol, weight in weights.items():
            if weight <= 1e-10:
                weights[str(symbol)] = 0
        
        # add crashProtectionSymbol to the finalWeights series with 0 if not already there
        if str(crashProtectionSymbol[0]) not in weights:
            weights[str(crashProtectionSymbol[0])] = 0
        
        return weights

class SymbolData:
    
    ''' Contain data specific to a symbol required by this model '''
    
    def __init__(self, symbol):
        
        self.Symbol = symbol
        self.returnSeries = None
        self.momentumScore = None
        
    def CalculateMomentumScore(self, history):
        
        ''' Calculate the weighted average momentum score for each security '''
        
        self.returnSeries = history.loc[str(self.Symbol)]['close'].pct_change(periods = 1).dropna() # 1-day returns for last year
    
        cumRet1 = (self.returnSeries.tail(21).add(1).prod()) - 1 # 1-month momentum
        cumRet3 = (self.returnSeries.tail(63).add(1).prod()) - 1 # 3-month momentum
        cumRet6 = (self.returnSeries.tail(126).add(1).prod()) - 1 # 6-month momentum
        cumRet12 = (self.returnSeries.tail(252).add(1).prod()) - 1 # 12-month momentum
        
        self.momentumScore = (cumRet1 * 12 + cumRet3 * 4 + cumRet6 * 2 + cumRet12) # weighted average momentum