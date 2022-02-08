# -*- coding: utf-8 -*-



from qgis.PyQt.QtCore import (QCoreApplication, QVariant)
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingMultiStepFeedback,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingUtils,
                       QgsProcessingParameterVectorDestination,
                       QgsVectorDataProvider,
                       QgsVectorLayer,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterNumber,
                       QgsProcessingException,
                       edit)
from qgis import processing
import os

class createGrid(QgsProcessingAlgorithm):

    INPUT = 'SAM'
    GRID_SIZE = 'GRID_SIZE'
    GRID_OPTION = 'GRID_OPTION'
    OUTPUT = 'AGG_GRID'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return createGrid()

    def name(self):
        return 'createGrid'

    def displayName(self):
        return self.tr('Create aggregation grid')

    def group(self):
        return self.tr('Nature Braid for SEEA')

    def groupId(self):
        return 'NBScripts'

    def shortHelpString(self):
        return self.tr("Create aggregation grid")

    def initAlgorithm(self, config=None):
        
        self.addParameter(
            QgsProcessingParameterVectorLayer(
            self.INPUT,
            self.tr('Study area mask'),
            types=[QgsProcessing.TypeVectorPolygon]
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
            self.GRID_SIZE,
            self.tr('Cell size in projection units'),
            type=QgsProcessingParameterNumber.Double,
            defaultValue=1000.0)
        )

        self.addParameter(
            QgsProcessingParameterEnum(
            self.GRID_OPTION,
            self.tr('Grid coverage'),
            options=[self.tr('Rectangular, covering full extent of boundary feature class'), self.tr('Grid covers area bounded by boundary feature class only')],
            defaultValue=0,
            optional=True)
        )

        self.addParameter(
            QgsProcessingParameterVectorDestination(
            self.OUTPUT,
            self.tr('Aggregation grid')
            )
        )
        
    def processAlgorithm(self, parameters, context, model_feedback):
        #from .NB_modules import cleanFields

        # Final inputs and outputs
        SAM = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        GRID_SIZE = self.parameterAsDouble(parameters, self.GRID_SIZE, context)
        GRID_OPTION = self.parameterAsEnum(parameters, self.GRID_OPTION, context)
        AGG_GRID = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)        
        
        # Intermediate files
        tempFolder = os.path.join(QgsProcessingUtils.tempFolder(), 'aggregation')
        if not os.path.exists(tempFolder):
            os.mkdir(tempFolder)
        gridInitial = os.path.join(tempFolder, 'gridInitial.shp')
        vectorOverlap = os.path.join(tempFolder, 'vectorOverlap.shp')

        feedback = QgsProcessingMultiStepFeedback(2, model_feedback)
        results = {}
        outputs = {}

        # Check that the CRS is projected coordinate system
        model_feedback.pushInfo('Checking coordinate system...')
        samCRS = SAM.crs()
        samGeo = SAM.crs().isGeographic()
        samUnits = SAM.crs().mapUnits()
        samExtent = SAM.extent()

        if samGeo == True:
            raise QgsProcessingException(self.tr("Opening dataset must be in a projected CRS"))

        if samUnits != 0:
            # if it's not in metres
            raise QgsProcessingException(self.tr("Opening dataset map units must be in meters"))

        if GRID_OPTION == 0:
            model_feedback.pushInfo('Rectangular option selected')
            # Create grid
            alg_params = {
                'TYPE': 2,
                'EXTENT': SAM,
                'HSPACING': GRID_SIZE,
                'VSPACING': GRID_SIZE,
                'CRS': samCRS,
                'OUTPUT': AGG_GRID
            }

            outputs['createGrid'] = processing.run(
                'native:creategrid',
                alg_params, context=context,
                feedback=feedback, is_child_algorithm=True
                )

            feedback.setCurrentStep(1)
            if feedback.isCanceled():
                return {}

        elif GRID_OPTION == 1:
            model_feedback.pushInfo('Study area extent selected')
            # Create grid
            alg_params = {
                'TYPE': 2,
                'EXTENT': SAM,
                'HSPACING': GRID_SIZE,
                'VSPACING': GRID_SIZE,
                'CRS': samCRS,
                'OUTPUT': gridInitial
            }

            outputs['createGrid'] = processing.run(
                'native:creategrid',
                alg_params, context=context,
                feedback=feedback, is_child_algorithm=True
                )

            feedback.setCurrentStep(1)
            if feedback.isCanceled():
                return {}

            alg_params = {
                'INPUT': gridInitial,
                'LAYERS': [SAM],
                'OUTPUT': AGG_GRID
            }

            outputs['overlap'] = processing.run(
                'native:calculatevectoroverlaps',
                alg_params, context=context,
                feedback=feedback, is_child_algorithm=True
                )

            # Go through feature class and erase the areas that don't overlap
            samName = SAM.name()
            areaField = str(samName) + '_area'

            overlapFC = QgsVectorLayer(AGG_GRID)
            caps = overlapFC.dataProvider().capabilities()
            feats = overlapFC.getFeatures()
            dfeats = []

            if caps & QgsVectorDataProvider.DeleteFeatures:
                for f in feats:
                    if f[areaField] == 0:
                        dfeats.append(f.id())

                res = overlapFC.dataProvider().deleteFeatures(dfeats)
                overlapFC.updateFields()

        else:
            raise QgsProcessingException('Invalid grid option')

        # Clean the feature class
        gridFC = QgsVectorLayer(AGG_GRID)
        fieldsToKeep = ['fid']
        
        allFields = [field.name() for field in gridFC.fields()]
        fieldsToRemove = list(set(allFields) - set(fieldsToKeep))

        idxRemove = []
        for field in fieldsToRemove:
            idx = allFields.index(field)
            idxRemove.append(idx)
        
        caps = gridFC.dataProvider().capabilities()
        if caps & QgsVectorDataProvider.DeleteAttributes:
            res = gridFC.dataProvider().deleteAttributes(idxRemove)
            gridFC.updateFields()
        
        results[self.OUTPUT] = AGG_GRID
        
        return results
