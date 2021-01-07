from clr import AddReference
AddReference("System")
AddReference("QuantConnect.Common")
AddReference("QuantConnect.Algorithm")
AddReference("QuantConnect.Algorithm.Framework")

from System import *
from QuantConnect import *
from QuantConnect.Algorithm import *
from QuantConnect.Algorithm.Framework import *
from QuantConnect.Algorithm.Framework.Alphas import AlphaModel, Insight, InsightType, InsightDirection

class LongOnlyMomentumAlphaCreationModel(AlphaModel):
    
    '''
    Description:
        - Every N days, this Alpha model calculates the momentum score of each risky asset in the Universe
            The momentum score is a weighted average of cumulative returns: (1-month * 12) + (3-month * 4) + (6-month * 2) + (12-month * 1) 
        - This Alpha model then creates InsightDirection.Up (to go Long) for a duration of a trading bar, every day for the selected top momentum securities
    Details:
        The important thing to understand here is the concept of Insight:
            - A prediction about the future of the security, indicating an expected Up, Down or Flat move
            - This prediction has an expiration time/date, meaning we think the insight holds for some amount of time
            - In the case of a constant long-only strategy, we are just updating every day the Up prediction for another extra day
            - In other words, every day we are making the conscious decision of staying invested in the security one more day
    '''

    def __init__(self, riskyTickers, crashProtectionTicker, canaryTickers, topMomentum = 5, rebalancingPeriod = Expiry.EndOfMonth):
        
        self.riskyTickers = riskyTickers # risky tickers to use for momentum asset allocation
        self.crashProtectionTicker = crashProtectionTicker # this ticker will also be part of momentum asset allocation,
                                                            # but it's a special asset that will get the crash protection allocation when needed
        self.canaryTickers = canaryTickers # canary tickers to avoid in momentum calculations, but we need to subscribe to them
        self.topMomentum = topMomentum # number of top momentum securities to keep
        self.rebalancingPeriod = rebalancingPeriod # the rebalancing function
        
        self.insightExpiry = Time.Multiply(Extensions.ToTimeSpan(Resolution.Daily), 0.25) # insight duration
        self.insightDirection = InsightDirection.Up # insight direction
        
        self.securities = [] # list to store securities to consider
        self.topMomentumSecurities = {} # empty dictionary to store top momentum securities
        
        self.rebalancingTime = None
        
    def Update(self, algorithm, data):
        
        if self.rebalancingTime is None:
            # get next rebalancing time
            self.rebalancingTime = self.rebalancingPeriod(algorithm.Time)
        
        ### calculate momentum scores (every N number of trading days) --------------------------------------------------------
        
        if algorithm.Time >= self.rebalancingTime:
            algorithm.Log('(Alpha) time to calculate the momentum securities')
            
            ### get symbols ---------------------------------------------------------------------------------------------------
        
            # risky symbols
            riskySymbols = [x.Symbol for x in self.securities if x.Symbol.Value in self.riskyTickers]
            algorithm.Log('(Alpha) number of risky assets: ' + str(len(riskySymbols)))
            # crash protection symbol
            crashProtectionSymbol = [x.Symbol for x in self.securities if x.Symbol.Value in self.crashProtectionTicker]
            algorithm.Log('(Alpha) number of crash protection assets: ' + str(len(crashProtectionSymbol)))
            
            # combine the two lists to get relevant symbols for momentum calculations
            relevantSymbols = riskySymbols + crashProtectionSymbol
            algorithm.Log('(Alpha) number of relevant assets for trading: ' + str(len(relevantSymbols)))
            
            # canary symbols
            canarySymbols = [x.Symbol for x in self.securities if x.Symbol.Value in self.canaryTickers]
            algorithm.Log('(Alpha) number of canary assets: ' + str(len(canarySymbols)))
            
            # combine all lists to get all symbols for calculations
            allSymbols = relevantSymbols + canarySymbols
            algorithm.Log('(Alpha) total number of assets considered for calculations: ' + str(len(allSymbols)))
            
            ### make momentum calculations ---------------------------------------------------------------------------------------
            
            # create empty dictionary to store calculations
            calculations = {}
            
            if len(allSymbols) > 0:
                # get historical prices for symbols
                history = algorithm.History(allSymbols, 253, Resolution.Daily)
                    
                for symbol in allSymbols:
                    # if symbol has no historical data continue the loop
                    if (str(symbol) not in history.index
                    or history.loc[str(symbol)].get('close') is None
                    or history.loc[str(symbol)].get('close').isna().any()):
                        algorithm.Log('(Alpha) no historical data for: ' + str(symbol.Value))
                        continue
                    else:
                        # add symbol to calculations
                        calculations[symbol] = SymbolData(symbol)
                        try:
                            # get momentum score
                            calculations[symbol].CalculateMomentumScore(history)
                        except Exception:
                            algorithm.Log('(Alpha) removing from Alpha calculations due to CalculateMomentumScore failing')
                            calculations.pop(symbol)
                            continue
                        
            calculatedSymbols = [x for x in calculations]
            algorithm.Log('(Alpha) checking the number of calculated symbols: ' + str(len(calculatedSymbols)))
            
            ### get the top momentum securities among risky assets (including crash protection asset) ---------------------------
    
            # perform Absolute Momentum: get the securities with positive momentum
            positiveMomentumSecurities = list(filter(lambda x: x.momentumScore > 0 and x.Symbol in relevantSymbols, calculations.values()))
            
            # perform Relative Momentum: sort descending by momentum score and select the top n
            self.topMomentumSecurities = sorted(positiveMomentumSecurities, key = lambda x: x.momentumScore, reverse = True)[:self.topMomentum]
            
            ### get percentage dedicated to risky assets ------------------------------------------------------------------------
            
            pctAggressive = self.CalculatePctAggressive(calculations, canarySymbols)
            algorithm.Log('(Alpha) pctAggressive: ' + str(pctAggressive))
            
            ### if percentage aggressive is less than 1 ------------------------------------------------------------
            ### we need to add the crashProtectionSecurity if it has positive absolute momentum
            
            crashProtectionSecurity = [x for x in self.securities if x.Symbol.Value in self.crashProtectionTicker]
            positiveMomentumSymbols = [x.Symbol for x in positiveMomentumSecurities]
            topMomentumSymbols = [x.Symbol for x in self.topMomentumSecurities]
            
            # if percentage aggressive is 0,
            # we only generate insights for the crash protection asset if it has positive absolute momentum;
            # if not, we don't send any insights
            if pctAggressive == 0:
                if crashProtectionSymbol[0] in positiveMomentumSymbols:
                    algorithm.Log('(Alpha) pctAggressive is 0 but crashProtectionSymbol has positive momentum so we add it')
                    self.topMomentumSecurities = crashProtectionSecurity
                else:
                    self.topMomentumSecurities = []
            
            # if percentage aggressive is positive but less than 1,
            # we need to make sure we are sending insights for the crash protection asset as well if it has positive absolute momentum
            elif pctAggressive < 1:
                if crashProtectionSymbol[0] in positiveMomentumSymbols and crashProtectionSymbol[0] not in topMomentumSymbols:
                    algorithm.Log('(Alpha) adding the crash protection asset to topMomentumSecurities')
                    self.topMomentumSecurities.append(crashProtectionSecurity[0])
            
            # get top momentum tickers for logs
            topMomentumTickers = [x.Symbol.Value for x in self.topMomentumSecurities]
            algorithm.Log('(Alpha) top securities: ' + str(topMomentumTickers))
            
            # update rebalancing time
            self.rebalancingTime = self.rebalancingPeriod(algorithm.Time)
            
        ### end of rebalance calculations ---------------------------------------------------------------------------------------
    
        ### generate insights ---------------------------------------------------------------------------------------------------
        
        insights = [] # list to store the new insights to be created
        
        # loop through active securities and generate insights
        for security in self.topMomentumSecurities:
            # check if there's new data for the security or we're already invested
            # if there's no new data but we're invested, we keep updating the insight since we don't really need to place orders
            if data.ContainsKey(security.Symbol) or algorithm.Portfolio[security.Symbol].Invested:
                # append the insights list with the prediction for each symbol
                insights.append(Insight.Price(security.Symbol, self.insightExpiry, self.insightDirection))
            else:
                algorithm.Log('(Portfolio) excluding security due to missing data: ' + str(security.Symbol.Value))
            
        return insights
        
    def OnSecuritiesChanged(self, algorithm, changes):
        
        '''
        Description:
            Event fired each time the we add/remove securities from the data feed
        Args:
            algorithm: The algorithm instance that experienced the change in securities
            changes: The security additions and removals from the algorithm
        '''
        
        # add new securities
        for added in changes.AddedSecurities:
            self.securities.append(added)

        # remove securities
        for removed in changes.RemovedSecurities:
            if removed in self.securities:
                self.securities.remove(removed)
                
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
        
class SymbolData:
    
    ''' Contain data specific to a symbol required by this model '''
    
    def __init__(self, symbol):
        
        self.Symbol = symbol

    def CalculateMomentumScore(self, history):
        
        ''' Calculate the weighted average momentum value for each security '''
        
        returnSeries = history.loc[str(self.Symbol)]['close'].pct_change(periods = 1).dropna() # 1-day returns for last year
        
        cumRet1 = (returnSeries.tail(21).add(1).prod()) - 1 # 1-month momentum
        cumRet3 = (returnSeries.tail(63).add(1).prod()) - 1 # 3-month momentum
        cumRet6 = (returnSeries.tail(126).add(1).prod()) - 1 # 6-month momentum
        cumRet12 = (returnSeries.tail(252).add(1).prod()) - 1 # 12-month momentum
        
        self.momentumScore = (cumRet1 * 12 + cumRet3 * 4 + cumRet6 * 2 + cumRet12) # weighted average momentum