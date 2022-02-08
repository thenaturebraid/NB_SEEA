# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import (QCoreApplication, QVariant)
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingMultiStepFeedback,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingUtils,
                       QgsProcessingParameterField,
                       QgsProcessingParameterVectorDestination,
                       QgsVectorDataProvider,
                       QgsField,
                       QgsExpression,
                       QgsExpressionContext,
                       QgsExpressionContextUtils,
                       QgsVectorLayer,
                       QgsProcessingParameterBoolean,
                       QgsVectorFileWriter,
                       QgsSpatialIndex,
                       QgsProcessingException,
                       edit)
from qgis import processing
import os
import numpy as np
from datetime import datetime

class calcRichness(QgsProcessingAlgorithm):

    INPUT = 'AGG_DATA'
    AGG_FIELD = 'AGG_FIELD'
    AGG_GRID = 'AGG_GRID'
    COVERAGE_OPTION = 'COVERAGE_OPTION'
    OUTPUT = 'RICH_GRID'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return calcRichness()

    def name(self):
        return 'calcRichness'

    def displayName(self):
        return self.tr('Calculate aggregate habitat statistics')

    def group(self):
        return self.tr('Nature Braid for SEEA')

    def groupId(self):
        return 'NBScripts'

    def shortHelpString(self):
        return self.tr("Calculate aggregate habitat statistics")

    def initAlgorithm(self, config=None):
        
        self.addParameter(
            QgsProcessingParameterVectorLayer(
            self.INPUT,
            self.tr('Data to aggregate'),
            types=[QgsProcessing.TypeVectorPolygon]
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
            self.AGG_FIELD,
            self.tr('Classification column'),
            '',
            self.INPUT
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorLayer(
            self.AGG_GRID,
            self.tr('Aggregation units'),
            types=[QgsProcessing.TypeVectorPolygon]
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
            self.COVERAGE_OPTION,
            self.tr('Only consider aggregation units which fully lie within the study area')
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorDestination(
            self.OUTPUT,
            self.tr('Richness grid')
            )
        )
        
    def processAlgorithm(self, parameters, context, model_feedback):
        # Final inputs and outputs
        AGG_DATA = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        AGG_FIELD = self.parameterAsString(parameters, self.AGG_FIELD, context)
        AGG_GRID = self.parameterAsVectorLayer(parameters, self.AGG_GRID, context)
        COVERAGE_OPTION = self.parameterAsBool(parameters, self.COVERAGE_OPTION, context)
        RICH_GRID = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)
        
        # Intermediate files
        tempFolder = os.path.join(QgsProcessingUtils.tempFolder(), 'aggregation')
        if not os.path.exists(tempFolder):
            os.mkdir(tempFolder)
        
        sam = os.path.join(tempFolder, 'sam.shp')
        gridInitial = os.path.join(tempFolder, 'gridInitial.shp')
        gridMask = os.path.join(tempFolder, 'gridMask.shp')

        vectorOverlap = os.path.join(tempFolder, 'vectorOverlap.shp')

        feedback = QgsProcessingMultiStepFeedback(2, model_feedback)
        results = {}
        outputs = {}

        # Check that the CRS is projected coordinate system
        model_feedback.pushInfo('Checking coordinate system...')
        samCRS = AGG_GRID.crs()
        samGeo = AGG_GRID.crs().isGeographic()
        samUnits = AGG_GRID.crs().mapUnits()
        samExtent = AGG_GRID.extent()

        if samGeo == True:
            raise QgsProcessingException(self.tr("Aggregation units dataset must be in a projected CRS"))

        if samUnits != 0:
            # if it's not in metres
            raise QgsProcessingException(self.tr("Aggregation units map units must be in meters"))

        # Dissolve aggregation data to make one mask
        model_feedback.pushInfo('Dissolve aggregation data')

        alg_params = {
            'INPUT': AGG_DATA,
            'FIELD': [],
            'OUTPUT': sam
        }

        outputs['samDissolve'] = processing.run(
            'native:dissolve',
            alg_params, context=context,
            feedback=feedback, is_child_algorithm=True
        )

        feedback.setCurrentStep(1)
        if feedback.isCanceled():
            return {}

        if COVERAGE_OPTION == True:
            model_feedback.pushInfo('Considering units only fully within the mask')

            alg_params = {
                'INPUT': AGG_GRID,
                'LAYERS': [sam],
                'OUTPUT': gridInitial
            }

            outputs['overlap'] = processing.run(
                'native:calculatevectoroverlaps',
                alg_params, context=context,
                feedback=feedback, is_child_algorithm=True
            )
            
            # Go through feature class and select only those with 100%
            percentField = 'sam_pc'
            maskFC = QgsVectorLayer(gridInitial)
            caps = maskFC.dataProvider().capabilities()
            feats = maskFC.getFeatures()
            dfeats = []

            if caps & QgsVectorDataProvider.DeleteFeatures:
                for f in feats:
                    if f[percentField] < 100:
                        dfeats.append(f.id())

                res = maskFC.dataProvider().deleteFeatures(dfeats)
                maskFC.updateFields()

        else:
            model_feedback.pushInfo('Considering all aggregation units')

            writer = QgsVectorFileWriter.writeAsVectorFormat(AGG_GRID, gridInitial, 'utf-8', driverName='ESRI Shapefile')
            del(writer)

        # Check the number of features in the new mask
        maskFC = QgsVectorLayer(gridInitial)
        maskFeatures = maskFC.featureCount()

        # If number of features == 0, throw error
        if maskFeatures == 0:
            raise QgsProcessingException(self.tr("Aggregation unit feature class does not have any aggregation units intersecting the study area"))

        outputStats = []

        # Clean grid of all fields
        fieldsToKeep = ['fid', 'id']
        allFields = [field.name() for field in maskFC.fields()]
        fieldsToRemove = list(set(allFields) - set(fieldsToKeep))

        idxRemove = []
        for field in fieldsToRemove:
            idx = allFields.index(field)
            idxRemove.append(idx)
        
        caps = maskFC.dataProvider().capabilities()
        if caps & QgsVectorDataProvider.DeleteAttributes:
            res = maskFC.dataProvider().deleteAttributes(idxRemove)
            maskFC.updateFields()

        # Calculate the size of each aggregation unit in km2
        # area_km2
        if caps & QgsVectorDataProvider.AddAttributes:
            res = maskFC.dataProvider().addAttributes([QgsField('area_km2', QVariant.Double)])
            maskFC.updateFields()

        expContext = QgsExpressionContext()
        expContext.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(maskFC))
        exp1 = QgsExpression('area($geometry) / 1000000')

        with edit(maskFC):
            for f in maskFC.getFeatures():
                expContext.setFeature(f)
                f['area_km2'] = exp1.evaluate(expContext)
                maskFC.updateFeature(f)

        # Initialise some variables
        unitNo = 0
        numCovers = []
        shannonIndex = []
        inverseSimpsonsIndex =[]
        meanPatchAreas = []

        # Loop through each unit/square
        
        # Make folder to hold individual shapefiles
        timeNow = datetime.now()
        folderName = timeNow.strftime('%Y%m%d_%H%M%S')
        unitFolder = os.path.join(tempFolder, folderName)
        os.mkdir(unitFolder)

        for f in maskFC.getFeatures():
            unitNo += 1
            
            model_feedback.pushInfo("Aggregating data from unit " + str(unitNo) + " of " + str(maskFeatures))
            
            # Export as individual square
            featureID = f.id()
            featureSHP = 'unit' + str(featureID) + '.shp'
            featureFN = os.path.join(unitFolder, featureSHP)
            maskFC.select([featureID])
            writer = QgsVectorFileWriter.writeAsVectorFormat(maskFC, featureFN, 'utf-8', driverName='ESRI Shapefile', onlySelected=True)
            del(writer)
            maskFC.removeSelection()
            
            index = QgsSpatialIndex()
            index.insertFeature(f)

            unitFC = QgsVectorLayer()
            unitSize = f['area_km2']

            dataSHP = 'data' + str(featureID) + '.shp'
            dataFN = os.path.join(unitFolder, dataSHP)

            # Clip the aggregation data to the single unit
            alg_params = {
                'INPUT': AGG_DATA,
                'OVERLAY': featureFN,
                'OUTPUT': dataFN
            }

            clipID = 'clip' + str(featureID)
            outputs[clipID] = processing.run(
                'native:clip',
                alg_params, context=context,
                feedback=feedback, is_child_algorithm=True
            )
            
            # index.insertFeature(QgsVectorLayer(dataFN))

            feedback.setCurrentStep(2)
            if feedback.isCanceled():
                return {}

            ##################
            ### Patch area ###
            ##################

            # Calculate the area in hectares for patch area
            dataClip = QgsVectorLayer(dataFN)
            fields = [field.name() for field in dataClip.fields()]

            caps = dataClip.dataProvider().capabilities()
            if caps & QgsVectorDataProvider.AddAttributes:
                if 'area_ha' in fields:
                    idx = fields.index('area_ha')
                    res = dataClip.dataProvider().deleteAttributes([idx])

                res = dataClip.dataProvider().addAttributes([QgsField('area_ha', QVariant.Double)])
                dataClip.updateFields()

            expContext = QgsExpressionContext()
            expContext.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(dataClip))
            exp1 = QgsExpression('area($geometry) / 10000')

            patchAreas = []

            with edit(dataClip):
                for feat in dataClip.getFeatures():
                    expContext.setFeature(feat)
                    feat['area_ha'] = exp1.evaluate(expContext)
                    patchAreas.append(float(feat['area_ha']))
                    dataClip.updateFeature(feat)

            if len(patchAreas) == 0:
                meanPatchArea = 0
            else:
                meanPatchArea = np.mean(patchAreas)

            meanPatchAreas.append(meanPatchArea)

            ##########################
            ### Other metrics area ###
            ##########################

            dissolveSHP = 'dissolve' + str(featureID) + '.shp'
            dissolveFN = os.path.join(unitFolder, dissolveSHP)

            # Dissolved clipped area and calculate area in km2
            alg_params = {
                'INPUT': dataClip,
                'FIELD':[AGG_FIELD],
                'OUTPUT': dissolveFN
            }

            dissolveID = 'dissolve' + str(featureID)
            outputs[dissolveID] = processing.run(
                'native:dissolve',
                alg_params, context=context,
                feedback=feedback, is_child_algorithm=True
            )

            # Calculate the area in km2 for each LC
            dissolveFC = QgsVectorLayer(dissolveFN)
            fields = [field.name() for field in dissolveFC.fields()]

            caps = dissolveFC.dataProvider().capabilities()
            if caps & QgsVectorDataProvider.AddAttributes:
                if 'area_km2' in fields:
                    idx = fields.index('area_km2')
                    res = dissolveFC.dataProvider().deleteAttributes([idx])

                res = dissolveFC.dataProvider().addAttributes([QgsField('area_km2', QVariant.Double)])
                dissolveFC.updateFields()

            expContext = QgsExpressionContext()
            expContext.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(dissolveFC))
            exp2 = QgsExpression('area($geometry) / 1000000')

            classificationsCount = 0
            probOcc = []

            with edit(dissolveFC):
                for feat in dissolveFC.getFeatures():
                    expContext.setFeature(feat)
                    feat['area_km2'] = exp2.evaluate(expContext)
                    classificationsCount += 1
                    probOcc.append(float(feat['area_km2']) / float(unitSize))
                    dissolveFC.updateFeature(feat)

            if len(probOcc) == 0:
                shannon = -1
                inverseSimpsons = -1
            else:
                shannon = -sum(probOcc * np.log(probOcc))
                inverseSimpsons = 1 / sum(np.array(probOcc) * np.array(probOcc))

            shannonIndex.append(shannon)
            inverseSimpsonsIndex.append(inverseSimpsons)
            numCovers.append(classificationsCount)
        
        fields = [field.name() for field in maskFC.fields()]
        fieldsToRemove = ['NUM_COVERS', 'SHANNON', 'INVSIMPSON', 'MEANPATCH']

        caps = dataClip.dataProvider().capabilities()
        if caps & QgsVectorDataProvider.AddAttributes:
            for field in fieldsToRemove:
                if field in fields:
                    idx = fields.index(field)
                    res = maskFC.dataProvider().deleteAttributes([idx])

                if field == 'NUM_COVERS':
                    res = maskFC.dataProvider().addAttributes([QgsField(field, QVariant.Int)])
                    maskFC.updateFields()

                else:
                    res = maskFC.dataProvider().addAttributes([QgsField(field, QVariant.Double)])
                    maskFC.updateFields()

        
        with edit(maskFC):
            for f in maskFC.getFeatures():
                featureID = f.id()
                f['NUM_COVERS'] = numCovers[featureID]
                f['SHANNON'] = float(shannonIndex[featureID])
                f['INVSIMPSON'] = float(inverseSimpsonsIndex[featureID])
                f['MEANPATCH'] = float(meanPatchAreas[featureID])
                maskFC.updateFeature(f)

        alg_params = {
            'INPUT': maskFC,
            'OUTPUT': RICH_GRID
        }

        outputs['copyOver'] = processing.run(
            'native:savefeatures',
            alg_params, context=context,
            feedback=feedback, is_child_algorithm=True
        )

        feedback.setCurrentStep(3)
        if feedback.isCanceled():
            return {}

        #writer = QgsVectorFileWriter.writeAsVectorFormat(maskFC, RICH_GRID, 'utf-8', driverName='ESRI Shapefile')
        #del(writer)

        results[self.OUTPUT] = RICH_GRID
        
        return results
