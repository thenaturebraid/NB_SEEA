'''
Nature Braid for SEEA

IUCN Red List Processing Tool
'''

from qgis.PyQt.QtCore import (QCoreApplication, QVariant)
from qgis.core import (QgsProcessing,
                       QgsProcessingException,
                       QgsProcessingAlgorithm,
                       QgsProcessingMultiStepFeedback,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingUtils,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterRasterDestination,
                       QgsVectorFileWriter,
                       QgsVectorLayer,
                       QgsVectorDataProvider,
                       QgsField,
                       QgsRasterLayer,                       
                       edit
                       )
from qgis.analysis import QgsRasterCalculator, QgsRasterCalculatorEntry
from qgis import processing
import os
from datetime import datetime

class calcIUCNRichness(QgsProcessingAlgorithm):
    INPUT = 'IUCN_SHP'
    SAM = 'SAM'
    OUTPUT_RES = 'OUTPUT_RES'
    OUTPUT = 'RICH_RAS'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return calcIUCNRichness()

    def name(self):
        return 'calcIUCNRichness'

    def displayName(self):
        return self.tr('Calculate IUCN species richness')

    def group(self):
        return self.tr('Nature Braid for SEEA')

    def groupId(self):
        return 'NBScripts'

    def shortHelpString(self):
        return self.tr("Calculate IUCN species richness")

    def initAlgorithm(self, config=None):
        
        self.addParameter(
            QgsProcessingParameterVectorLayer(
            self.INPUT,
            self.tr('IUCN species richness'),
            types=[QgsProcessing.TypeVectorPolygon]
            )
        )

        self.addParameter(
            QgsProcessingParameterVectorLayer(
            self.SAM,
            self.tr('Study area mask'),
            types=[QgsProcessing.TypeVectorPolygon]
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
            self.OUTPUT_RES,
            self.tr('Output resolution (degrees)'),
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.005)
        )

        self.addParameter(
            QgsProcessingParameterRasterDestination(
            self.OUTPUT,
            self.tr('Richness raster')
            )
        )
        
        
    def processAlgorithm(self, parameters, context, model_feedback):
        # Final inputs and outputs
        IUCN_SHP = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        SAM = self.parameterAsVectorLayer(parameters, self.SAM, context)
        OUTPUT_RES = self.parameterAsDouble(parameters, self.OUTPUT_RES, context)
        RICH_RAS = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)        
        
        # Temporary files
        timeNow = datetime.now()
        folderName = timeNow.strftime('%Y%m%d_%H%M%S')        
        tempFolder = os.path.join(QgsProcessingUtils.tempFolder(), folderName)
        if not os.path.exists(tempFolder):
            os.mkdir(tempFolder)

        sam_proj = os.path.join(tempFolder, 'sam.shp')
        sam_ras = os.path.join(tempFolder, 'sam_ras.tif')
        iucn_clipped = os.path.join(tempFolder, 'iucn_clipped.shp')
        addition_ras = os.path.join(tempFolder, 'addition_ras.tif')

        feedback = QgsProcessingMultiStepFeedback(2, model_feedback)
        results = {}
        outputs = {}

        # Check CRS with each other
        iucnCRS = IUCN_SHP.crs()
        samCRS = SAM.crs()

        if iucnCRS.authid() == samCRS.authid():
            # Same CRS, just copy over
            writer = QgsVectorFileWriter.writeAsVectorFormat(SAM, sam_proj, 'utf-8', driverName='ESRI Shapefile')
            del(writer)
        else:
            model_feedback.pushInfo('Reprojecting study area mask to IUCN coordinate system...')
            # Reproject SAM to IUCN CRS
            alg_params = {
                'INPUT': SAM,
                'TARGET_CRS': iucnCRS,
                'OUTPUT': sam_proj
            }

            outputs['projected'] = processing.run(
                'native:reprojectlayer',
                alg_params, context=context,
                feedback=feedback, is_child_algorithm=True
            )

        # Rasterize the study area mask
        alg_params = {
                'INPUT': sam_proj,
                'BURN': 1,
                'UNITS': 1,
                'WIDTH': OUTPUT_RES,
                'HEIGHT': OUTPUT_RES,
                'EXTENT': SAM.extent(),
                'NODATA': 0,
                'OUTPUT': sam_ras
            }

        outputs['rasterSAM'] = processing.run(
            'gdal:rasterize',
            alg_params, context=context,
            feedback=feedback, is_child_algorithm=True
        )

        feedback.setCurrentStep(1)
        if feedback.isCanceled():
            return {}

        # Clip IUCN down (iucn_clipped)
        alg_params = {
            'INPUT': IUCN_SHP,
            'OVERLAY': sam_proj,
            'OUTPUT': iucn_clipped
        }

        outputs['clipIUCN'] = processing.run(
            'native:clip',
            alg_params, context=context,
            feedback=feedback, is_child_algorithm=True
        )

        feedback.setCurrentStep(2)
        if feedback.isCanceled():
            return {}

        # Add the Richness field (integer)
        iucnFC = QgsVectorLayer(iucn_clipped)
        fields = [field.name() for field in iucnFC.fields()]

        caps = iucnFC.dataProvider().capabilities()
        if caps & QgsVectorDataProvider.AddAttributes:
            if 'Richness' in fields:
                idx = fields.index('Richness')
                res = iucnFC.dataProvider().deleteAttributes([idx])

            res = iucnFC.dataProvider().addAttributes([QgsField('Richness', QVariant.Int)])
            iucnFC.updateFields()

        # Give Richness all a value of 1
        with edit(iucnFC):
            for f in iucnFC.getFeatures():
                f['Richness'] = 1
                iucnFC.updateFeature(f)

        # Use the Split Vector Layer tool to split things up
        speciesFolder = os.path.join(tempFolder, 'speciesLayers')
        os.mkdir(speciesFolder)

        alg_params = {
            'INPUT': iucn_clipped,
            'FIELD': 'id_no',
            'FILE_TYPE': 0,
            'OUTPUT': speciesFolder
        }

        outputs['speciesLayers'] = processing.run(
            'native:splitvectorlayer',
            alg_params, context=context,
            feedback=feedback, is_child_algorithm=True
        )

        feedback.setCurrentStep(1)
        if feedback.isCanceled():
            return {}

        # Rasterize each of the the layers

        # Loop through each of the speciesLayers
        speciesLyrs = os.listdir(speciesFolder)

        # Make the output layer
        rasterFolder = os.path.join(tempFolder, 'rasterFolder')
        os.mkdir(rasterFolder)

        allSpecies = len(speciesLyrs)

        countSpecies = 0
        for lyr in speciesLyrs:
            info = 'Processing species ' + str(countSpecies) + ' of ' + str(allSpecies)
            model_feedback.pushInfo(info)
            inFN = os.path.join(speciesFolder, lyr)
            outID = 'raster' + str(countSpecies)
            outName = 'ras_' + str(countSpecies) + '.tif'
            outFN = os.path.join(rasterFolder, outName)
            countSpecies += 1

            alg_params = {
                'INPUT': inFN,
                'FIELD': 'Richness',
                'UNITS': 1,
                'WIDTH': OUTPUT_RES,
                'HEIGHT': OUTPUT_RES,
                'EXTENT': SAM.extent(),
                'NODATA': 0,
                'OUTPUT': outFN
            }

            outputs[outID] = processing.run(
                'gdal:rasterize',
                alg_params, context=context,
                feedback=feedback, is_child_algorithm=True
            )

            feedback.setCurrentStep(3 + countSpecies)
            if feedback.isCanceled():
                return {}

        step = (3 + countSpecies)

        # Loop through rasterised rasters
        speciesRasters = []
        for file in os.listdir(rasterFolder):
            if file.endswith('.tif'):
                speciesRasters.append(file)

        # Make the output layer
        reclassFolder = os.path.join(tempFolder, 'reclassFolder')
        os.mkdir(reclassFolder)

        totalRasters = len(speciesRasters)
        rasterCount = 0
        
        for lyr in speciesRasters:
            info = 'Processing raster ' + str(rasterCount) + ' of ' + str(totalRasters)
            model_feedback.pushInfo(info)

            inFN = os.path.join(rasterFolder, lyr)
            outID = 'reclass' + str(rasterCount)
            outName = 'reclass_' + str(rasterCount) + '.tif'
            
            outFN = os.path.join(reclassFolder, outName)
            rasterCount += 1
            step += 1

            alg_params = {
                'INPUT': inFN,
                'NODATA': -1,
                'OUTPUT': outFN
            }

            outputs[outID] = processing.run(
                'gdal:translate',
                alg_params, context=context,
                feedback=feedback, is_child_algorithm=True
            )

            feedback.setCurrentStep(step)
            if feedback.isCanceled():
                return {}
        
        # Loop through reclassified rasters
        reclassRasters = []
        for file in os.listdir(reclassFolder):
            if file.endswith('.tif'):
                fileName = os.path.join(reclassFolder, file)
                reclassRasters.append(fileName)

        rasterIDs = []

        #model_feedback.pushInfo('reclassRasters')
        #model_feedback.pushInfo(str(reclassRasters))

        layers = [QgsRasterLayer(str(raster)) for raster in reclassRasters]
        entries = []

        for i, layer in enumerate(layers, 1):
            entry = QgsRasterCalculatorEntry()
            entry.ref = f"layer{i}@1"
            entry.raster = layer
            entry.bandNumber = 1
            entries.append(entry)

        #model_feedback.pushInfo('entries')
        #model_feedback.pushInfo(str(entries))
        #model_feedback.pushInfo('rasterIDs')
        #model_feedback.pushInfo(str(rasterIDs))

        refs = [entry.ref for entry in entries]
        #model_feedback.pushInfo('refs')
        #model_feedback.pushInfo(str(refs))

        operation = ''

        for i in range(0, len(refs)):
            if i in [0, len(refs)]:
                # If it is the first or last raster
                operation += (str(refs[i]))
            else:
                operation += ' + ' + str(refs[i])

        #model_feedback.pushInfo('operation')
        #model_feedback.pushInfo(str(operation))
        
        # Add samRaster to the raster calculator
        samLyr = QgsRasterLayer(sam_ras)
        ras = QgsRasterCalculatorEntry()
        ras.ref = 'sam@1'
        ras.bandNumber = 1
        ras.raster = samLyr
        entries.append(ras)
        
        calc = QgsRasterCalculator(
            operation,
            addition_ras,
            "GTiff",
            samLyr.extent(),
            samLyr.width(),
            samLyr.height(),
            entries,
        )
        
        rasCalc_result = calc.processCalculation(feedback)
        if rasCalc_result == QgsRasterCalculator.ParserError:
            raise QgsProcessingException(self.tr("Error parsing formula"))
        elif rasCalc_result == QgsRasterCalculator.CalculationError:
            raise QgsProcessingException(self.tr("An error occurred while performing the calculation"))
        
        step += 1
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}
        
        #model_feedback.pushInfo('addition_ras')
        #model_feedback.pushInfo(str(addition_ras))
        
        # Export raster where 0 is NoData values
        entries = []

        samLyr = QgsRasterLayer(sam_ras)
        ras = QgsRasterCalculatorEntry()
        ras.ref = 'sam@1'
        ras.bandNumber = 1
        ras.raster = samLyr
        entries.append(ras)

        additionLyr = QgsRasterLayer(addition_ras)
        ras = QgsRasterCalculatorEntry()
        ras.ref = 'addition@1'
        ras.bandNumber = 1
        ras.raster = additionLyr
        entries.append(ras)

        # Reference: https://gis.stackexchange.com/questions/81640/how-to-set-all-pixels-with-value-0-to-nodata-in-dem-raster
        operation = '((addition@1 > 0) * addition@1) / ((addition@1 > 0) * 1 + (addition@1 <= 0) * 0)'

        calc = QgsRasterCalculator(
            operation,
            RICH_RAS,
            "GTiff",
            samLyr.extent(),
            samLyr.width(),
            samLyr.height(),
            entries,
        )
        
        rasCalc_result = calc.processCalculation(feedback)
        if rasCalc_result == QgsRasterCalculator.ParserError:
            raise QgsProcessingException(self.tr("Error parsing formula"))
        elif rasCalc_result == QgsRasterCalculator.CalculationError:
            raise QgsProcessingException(self.tr("An error occurred while performing the calculation"))
        
        step += 1
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}
        
        results[self.OUTPUT] = RICH_RAS
        
        return results
