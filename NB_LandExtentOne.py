# -*- coding: utf-8 -*-



from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing,
                       QgsProcessingException,
                       QgsProcessingAlgorithm,
                       QgsProcessingMultiStepFeedback,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingUtils,
                       QgsProcessingParameterField,
                       QgsProcessingParameterVectorDestination,
                       QgsProcessingParameterFileDestination
                       )
from qgis import processing
import os

class CalcLandExtentOneFile(QgsProcessingAlgorithm):

    INPUT = 'LC_SHP'
    LC_OPENING = 'LC_OPENING'
    LC_CLOSING = 'LC_CLOSING'
    LC_NAME = 'LC_NAME'
    OUTPUT_CSV = 'OUTPUT_CSV'
    OUTPUT = 'LC_ACCOUNTS'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return CalcLandExtentOneFile()

    def name(self):
        return 'CalcLandExtentOneFile'

    def displayName(self):
        return self.tr('Calculate land extent accounts (one land cover or extent dataset)')

    def group(self):
        return self.tr('Nature Braid for SEEA')

    def groupId(self):
        return 'NBScripts'

    def shortHelpString(self):
        return self.tr("Calculate land extent accounts from one land cover or extent dataset")

    def initAlgorithm(self, config=None):
        
        self.addParameter(
            QgsProcessingParameterVectorLayer(
            self.INPUT,
            self.tr('Land cover or extent dataset: one file with multiple fields'),
            types=[QgsProcessing.TypeVectorPolygon]
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
            self.LC_OPENING,
            self.tr('Opening year land extent field'),
            '',
            self.INPUT
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
            self.LC_CLOSING,
            self.tr('Closing year land extent field'),
            '',
            self.INPUT
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
            self.LC_NAME,
            self.tr('Field containing land cover class name from opening dataset'),
            '',
            self.INPUT
            )
        )

        self.addParameter(
            QgsProcessingParameterFileDestination(
            self.OUTPUT_CSV,
            self.tr('Land cover/extent transition matrix'),
            'CSV files (*.csv)'
            )
        )
        
        self.addParameter(
            QgsProcessingParameterVectorDestination(
            self.OUTPUT,
            self.tr('Land cover accounts')
            )
        )
        
    def processAlgorithm(self, parameters, context, model_feedback):
        # Final inputs and outputs
        LC_SHP = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        LC_OPENING = self.parameterAsString(parameters, self.LC_OPENING, context)
        LC_CLOSING = self.parameterAsString(parameters, self.LC_CLOSING, context)
        LC_ACCOUNTS = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)        
        OUTPUT_CSV = self.parameterAsFileOutput(parameters, self.OUTPUT_CSV, context)
        LC_NAME =  self.parameterAsString(parameters, self.LC_NAME, context)

        # Temporary files
        tempFolder = os.path.join(QgsProcessingUtils.tempFolder(), 'calc_lc_one')
        if not os.path.exists(tempFolder):
            os.mkdir(tempFolder)
        openingLC = os.path.join(tempFolder, 'openingLC.shp')
        closingLC = os.path.join(tempFolder, 'closingLC.shp')

        # Check that the CRS is projected coordinate system
        landCoverGeo = LC_SHP.crs().isGeographic()
        landCoverUnits = LC_SHP.crs().mapUnits()

        if landCoverGeo == True:
            raise QgsProcessingException(self.tr("Opening dataset must be in a projected CRS"))

        if landCoverUnits != 0:
            # if it's not in metres
            raise QgsProcessingException(self.tr("Opening dataset map units must be in meters"))

        feedback = QgsProcessingMultiStepFeedback(2, model_feedback)
        results = {}
        outputs = {}

        # Dissolve opening LC
        alg_params = {'INPUT': LC_SHP,
            'FIELD':[LC_OPENING],
            'OUTPUT': openingLC
        }
        
        outputs['openingDissolve'] = processing.run(
            'native:dissolve',
            alg_params, context=context,
            feedback=feedback, is_child_algorithm=True
        )

        feedback.setCurrentStep(1)
        if feedback.isCanceled():
            return {}

        # Dissolve closing LC
        alg_params = {'INPUT': LC_SHP,
            'FIELD':[LC_CLOSING],
            'OUTPUT': closingLC
        }
        
        outputs['openingDissolve'] = processing.run(
            'native:dissolve',
            alg_params, context=context,
            feedback=feedback, is_child_algorithm=True
        )

        feedback.setCurrentStep(2)
        if feedback.isCanceled():
            return {}

        # Call the calculation function here
        alg_params = {'LC_OPENING_SHP': openingLC,
            'LC_OPENING': LC_OPENING,
            'LC_CLOSING_SHP': closingLC,
            'LC_CLOSING': LC_CLOSING,
            'LC_NAME': LC_NAME,
            'OUTPUT_CSV': OUTPUT_CSV,
            'OUTPUT_LC': LC_ACCOUNTS
        }
        
        outputs['accCalc'] = processing.run(
            'script:CalcLandExtentCalc',
            alg_params, context=context,
            feedback=feedback, is_child_algorithm=True
        )
        
        results[self.OUTPUT] = LC_ACCOUNTS
        results[self.OUTPUT_CSV] = OUTPUT_CSV
        
        return results
