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

class CalcLandExtentMultFiles(QgsProcessingAlgorithm):

    LC_OPENING_SHP = 'LC_OPENING_SHP'
    LC_OPENING = 'LC_OPENING'
    LC_CLOSING_SHP = 'LC_CLOSING_SHP'
    LC_CLOSING = 'LC_CLOSING'
    LC_NAME = 'LC_NAME'
    OUTPUT_CSV = 'OUTPUT_CSV'
    OUTPUT = 'LC_ACCOUNTS'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return CalcLandExtentMultFiles()

    def name(self):
        return 'CalcLandExtentMultFiles'

    def displayName(self):
        return self.tr('Calculate land extent accounts (two land cover or extent datasets)')

    def group(self):
        return self.tr('Nature Braid for SEEA')

    def groupId(self):
        return 'NBScripts'

    def shortHelpString(self):
        return self.tr("Calculate land extent accounts from two land cover or extent datasets")

    def initAlgorithm(self, config=None):
        
        self.addParameter(
            QgsProcessingParameterVectorLayer(
            self.LC_OPENING_SHP,
            self.tr('Opening land cover or extent dataset'),
            types=[QgsProcessing.TypeVectorPolygon]
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
            self.LC_OPENING,
            self.tr('Opening year land extent field'),
            '',
            self.LC_OPENING_SHP
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorLayer(
            self.LC_CLOSING_SHP,
            self.tr('Closing land cover or extent dataset'),
            types=[QgsProcessing.TypeVectorPolygon]
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
            self.LC_CLOSING,
            self.tr('Closing year land extent field'),
            '',
            self.LC_CLOSING_SHP
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
            self.LC_NAME,
            self.tr('Field containing land cover class name from opening dataset'),
            '',
            self.LC_OPENING_SHP
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
        LC_OPENING_SHP = self.parameterAsVectorLayer(parameters, self.LC_OPENING_SHP, context)
        LC_OPENING = self.parameterAsString(parameters, self.LC_OPENING, context)
        LC_CLOSING_SHP = self.parameterAsVectorLayer(parameters, self.LC_CLOSING_SHP, context)
        LC_CLOSING = self.parameterAsString(parameters, self.LC_CLOSING, context)
        LC_ACCOUNTS = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)        
        OUTPUT_CSV = self.parameterAsFileOutput(parameters, self.OUTPUT_CSV, context)
        LC_NAME =  self.parameterAsString(parameters, self.LC_NAME, context)

        # Temporary files
        tempFolder = os.path.join(QgsProcessingUtils.tempFolder(), 'calc_lc_two')
        if not os.path.exists(tempFolder):
            os.mkdir(tempFolder)
        openingLC = os.path.join(tempFolder, 'openingLC.shp')
        closingLC = os.path.join(tempFolder, 'closingLC.shp')

        feedback = QgsProcessingMultiStepFeedback(2, model_feedback)
        results = {}
        outputs = {}

        # Check that the CRS is projected coordinate system
        openGeo = LC_OPENING_SHP.crs().isGeographic()
        openUnits = LC_OPENING_SHP.crs().mapUnits()

        if openGeo == True:
            raise QgsProcessingException(self.tr("Opening dataset must be in a projected CRS"))

        if openUnits != 0:
            # if it's not in metres
            raise QgsProcessingException(self.tr("Opening dataset map units must be in meters"))

        closeGeo = LC_CLOSING_SHP.crs().isGeographic()
        closeUnits = LC_CLOSING_SHP.crs().mapUnits()

        if closeGeo == True:
            raise QgsProcessingException(self.tr("Opening dataset must be in a projected CRS"))

        if closeUnits != 0:
            # if it's not in metres
            raise QgsProcessingException(self.tr("Opening dataset map units must be in meters"))

        # Dissolve opening LC
        alg_params = {'INPUT': LC_OPENING_SHP,
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
        alg_params = {'INPUT': LC_CLOSING_SHP,
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
