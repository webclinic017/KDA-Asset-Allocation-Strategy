### PRODUCT INFORMATION --------------------------------------------------------------------------------
# Copyright InnoQuantivity.com, granted to the public domain.
# Use entirely at your own risk.
# This algorithm contains open source code from other sources and no claim is being made to such code.
# Do not remove this copyright notice.
### ----------------------------------------------------------------------------------------------------

from LongOnlyMomentumAlphaCreation import LongOnlyMomentumAlphaCreationModel
from OptimizationPortfolioConstruction import OptimizationPortfolioConstructionModel
from ImmediateExecutionWithLogs import ImmediateExecutionWithLogsModel

class KDAAssetAllocationFrameworkAlgorithm(QCAlgorithmFramework):
    
    '''
    Trading Logic:
        - Implementation of https://quantstrattrader.wordpress.com/2019/01/24/right-now-its-kda-asset-allocation/
        - This algorithm is a long-only dual momentum asset class strategy as described in the link above
    Modules:
        Universe: Manual input of tickers
        Alpha:
            - Calculates momentum score for each security at the end of every period (see Alpha module for details)
            - Constant creation of Up Insights every trading bar during the period for the top securities
        Portfolio: Minimum Variance (optimal weights to minimize portfolio variance)
            - See Portfolio module for details
        Execution: Immediate Execution with Market Orders
        Risk: Null
    '''

    def Initialize(self):
        
        ### user-defined inputs --------------------------------------------------------------
        
        # set timeframe for backtest and starting cash
        self.SetStartDate(2005, 1, 1)   # set start date
        #self.SetEndDate(2016, 1, 1)    # set end date
        self.SetCash(100000)            # set strategy cash
        
        # add tickers for risky assets for momentum asset allocation
        riskyTickers = ['SPY',  # US equities
                        'VGK',  # European equities
                        'EWJ',  # Japanese equities
                        'EEM',  # Emerging market equities
                        'VNQ',  # US REITs
                        'RWX',  # International REITs
                        'TLT',  # US 30-year Treasuries
                        'DBC',  # Commodities
                        'GLD',  # Gold
                        ]
        
        # this ticker will also be part of risky assets for momentum asset allocation,
        # but it's a special asset that will get the crash protection allocation when needed
        crashProtectionTicker = ['IEF'] # US 10-year Treasuries 
                    
        # add tickers for canary assets          
        canaryTickers = ["VWO", # Vanguard FTSE Emerging Markets ETF
                        "BND"   # Vanguard Total Bond Market ETF
                        ]
        
        # number of top momentum securities to keep
        topMomentum = 5
        
        # select the logic for rebalancing period
        # options are:
        #   - Date rules (for the first trading day of period): Expiry.EndOfDay, Expiry.EndOfWeek, Expiry.EndOfMonth, Expiry.EndOfQuarter, Expiry.EndOfYear
        rebalancingPeriod = Expiry.EndOfMonth
        
        # objective function for portfolio optimizer
        # options are: return (maximize portfolio return), std (minimize portfolio Standard Deviation) and sharpe (maximize portfolio sharpe ratio)
        objectiveFunction = 'std'
        
        ### -----------------------------------------------------------------------------------

        # set the brokerage model for slippage and fees
        self.SetBrokerageModel(AlphaStreamsBrokerageModel())
        
        # set requested data resolution and disable fill forward data
        self.UniverseSettings.Resolution = Resolution.Daily
        
        # combine all lists of tickers
        allTickers = riskyTickers + crashProtectionTicker + canaryTickers
        
        # let's plot the series of optimal weights
        optWeightsPlot = Chart('Chart Optimal Weights %')
        
        symbols = []
        # loop through the tickers list and create symbols for the universe
        for i in range(len(allTickers)):
            symbols.append(Symbol.Create(allTickers[i], SecurityType.Equity, Market.USA))
            optWeightsPlot.AddSeries(Series(allTickers[i], SeriesType.Line, '%'))
        self.AddChart(optWeightsPlot)
        
        # select modules
        self.SetUniverseSelection(ManualUniverseSelectionModel(symbols))
        self.SetAlpha(LongOnlyMomentumAlphaCreationModel(riskyTickers = riskyTickers,
                                                        crashProtectionTicker = crashProtectionTicker,
                                                        canaryTickers = canaryTickers,
                                                        topMomentum = topMomentum,
                                                        rebalancingPeriod = rebalancingPeriod))
        self.SetPortfolioConstruction(OptimizationPortfolioConstructionModel(crashProtectionTicker = crashProtectionTicker,
                                                                            canaryTickers = canaryTickers,
                                                                            topMomentum = topMomentum,
                                                                            objectiveFunction = objectiveFunction,
                                                                            rebalancingPeriod = rebalancingPeriod))
        self.SetExecution(ImmediateExecutionWithLogsModel())
        self.SetRiskManagement(NullRiskManagementModel())