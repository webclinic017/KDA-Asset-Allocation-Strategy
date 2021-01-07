import numpy as np
from scipy.optimize import minimize

class CustomPortfolioOptimizer:
    
    '''
    Description:
        Implementation of a custom optimizer that calculates the weights for each asset to optimize a given objective function
    Details:
        Optimization can be:
            - Maximize Portfolio Return
            - Minimize Portfolio Standard Deviation
            - Maximize Portfolio Sharpe Ratio
        Constraints:
            - Weights must be between some given boundaries
            - Weights must sum to 1
    '''
    
    def __init__(self, 
                 minWeight = -1,
                 maxWeight = 1,
                 objFunction = 'std'):
                     
        '''
        Description:
            Initialize the CustomPortfolioOptimizer
        Args:
            minWeight(float): The lower bound on portfolio weights
            maxWeight(float): The upper bound on portfolio weights
            objFunction: The objective function to optimize (return, std, sharpe)
        '''
        
        self.minWeight = minWeight
        self.maxWeight = maxWeight
        self.objFunction = objFunction

    def Optimize(self, historicalLogReturns, covariance = None):
        
        '''
        Description:
            Perform portfolio optimization using a provided matrix of historical returns and covariance (optional)
        Args:
            historicalLogReturns: Matrix of historical log-returns where each column represents a security and each row log-returns for the given date/time (size: K x N)
            covariance: Multi-dimensional array of double with the portfolio covariance of returns (size: K x K)
        Returns:
            Array of double with the portfolio weights (size: K x 1)
        '''
        
        # if no covariance is provided, calculate it using the historicalLogReturns
        if covariance is None:
            covariance = historicalLogReturns.cov()

        size = historicalLogReturns.columns.size # K x 1
        x0 = np.array(size * [1. / size])
        
        # apply equality constraints
        constraints = ({'type': 'eq', 'fun': lambda weights: self.GetBudgetConstraint(weights)})

        opt = minimize(lambda weights: self.ObjectiveFunction(weights, historicalLogReturns, covariance),   # Objective function
                        x0,                                                                                 # Initial guess
                        bounds = self.GetBoundaryConditions(size),                                          # Bounds for variables
                        constraints = constraints,                                                          # Constraints definition
                        method = 'SLSQP')                                                                   # Optimization method: Sequential Least Squares Programming
                        
        return opt['x']

    def ObjectiveFunction(self, weights, historicalLogReturns, covariance):
        
        '''
        Description:
            Compute the objective function
        Args:
            weights: Portfolio weights
            historicalLogReturns: Matrix of historical log-returns
            covariance: Covariance matrix of historical log-returns
        '''
        
        # calculate the annual return of portfolio
        annualizedPortfolioReturns = np.sum(historicalLogReturns.mean() * 252 * weights)

        # calculate the annual standard deviation of portfolio
        annualizedPortfolioStd = np.sqrt( np.dot(weights.T, np.dot(covariance * 252, weights)) )
        
        if annualizedPortfolioStd == 0:
            raise ValueError(f'CustomPortfolioOptimizer.ObjectiveFunction: annualizedPortfolioStd cannot be zero. Weights: {weights}')
        
        # calculate annual sharpe ratio of portfolio
        annualizedPortfolioSharpeRatio = (annualizedPortfolioReturns / annualizedPortfolioStd)
            
        if self.objFunction == 'sharpe':
            return -annualizedPortfolioSharpeRatio # convert to negative to be minimized
        elif self.objFunction == 'return':
            return -annualizedPortfolioReturns # convert to negative to be minimized
        elif self.objFunction == 'std':
            return annualizedPortfolioStd
        else:
            raise ValueError(f'CustomPortfolioOptimizer.ObjectiveFunction: objFunction input has to be one of sharpe, return or std')

    def GetBoundaryConditions(self, size):
        
        ''' Create the boundary condition for the portfolio weights '''
        
        return tuple((self.minWeight, self.maxWeight) for x in range(size))

    def GetBudgetConstraint(self, weights):
        
        ''' Define a budget constraint: the sum of the weights equal to 1 '''
        
        return np.sum(weights) - 1